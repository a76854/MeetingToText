/**
 * Browser audio capture for the recorder: media acquisition (mic / system /
 * merged mic+system), the PCM AudioWorklet graph, the volume meter, and the
 * teardown of all of it.
 *
 * This factory owns every AudioContext / AnalyserNode / AudioWorkletNode /
 * MediaStream handle the recording flow creates, so the orchestrator
 * (recorder.ts) never touches the Web Audio graph directly — it only asks
 * for a stream, starts the pipeline, and reports volume through a callback.
 *
 * No Vue imports on purpose: the volume level is pushed out through
 * `setOnVolume`, keeping this module about the MEDIA, not the UI state.
 */

export interface AcquiredMedia {
  /** acquired audio stream (mic-only, system-only, or the merged destination) */
  stream?: MediaStream
  /** user-facing degradation warning ('' when nothing degraded) */
  warning: string | null
}

export interface AudioCapture {
  /** getUserMedia/getDisplayMedia with noise-suppression constraints and mic+system merge */
  acquireMediaStream: (audioSource: string, noiseSuppression: boolean) => Promise<AcquiredMedia>
  /** PCM worklet graph; every chunk is handed to `onPcm` as Float32Array */
  startStreaming: (stream: MediaStream, onPcm: (chunk: Float32Array) => void) => Promise<void>
  /** volume meter only (local-mode fallback: no worklet, no PCM) */
  startVolumeOnly: (stream: MediaStream) => void
  /** disconnect graph nodes and close the AudioContext (stream/merge tracks stay) */
  teardownGraph: () => void
  /** release merge context and stop every acquired media track */
  teardownTracks: () => void
  /** the stream currently owned by this capture (null once torn down) */
  getStream: () => MediaStream | null
  /** AudioContext sample rate of the last successful graph (0 if none) */
  getSampleRate: () => number
  setOnVolume: (fn: (level: number) => void) => void
}

export function useAudioCapture(): AudioCapture {
  let audioCtx: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let workletNode: AudioWorkletNode | null = null
  let animFrame: number | null = null
  let stream: MediaStream | null = null
  let mergeCtx: AudioContext | null = null
  let onVolume = (_level: number) => {}

  function startVolumeMeter(an: AnalyserNode) {
    const dataArray = new Uint8Array(an.frequencyBinCount)
    function tick() {
      if (!analyser) return
      an.getByteFrequencyData(dataArray)
      const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length
      onVolume(Math.min(avg / 160, 1))
      animFrame = requestAnimationFrame(tick)
    }
    tick()
  }

  async function startStreaming(s: MediaStream, onPcm: (chunk: Float32Array) => void) {
    audioCtx = new AudioContext()
    await audioCtx.resume()
    await audioCtx.audioWorklet.addModule('/audio-processor.js')
    workletNode = new AudioWorkletNode(audioCtx, 'recorder-processor')

    const source = audioCtx.createMediaStreamSource(s)
    source.connect(workletNode)

    analyser = audioCtx.createAnalyser()
    analyser.fftSize = 256
    source.connect(analyser)

    const mute = audioCtx.createGain()
    mute.gain.value = 0
    workletNode.connect(mute)
    mute.connect(audioCtx.destination)

    workletNode.port.onmessage = (e: MessageEvent) => {
      onPcm(e.data as Float32Array)
    }

    startVolumeMeter(analyser)
  }

  function startVolumeOnly(s: MediaStream) {
    audioCtx = new AudioContext()
    const source = audioCtx.createMediaStreamSource(s)
    analyser = audioCtx.createAnalyser()
    analyser.fftSize = 256
    source.connect(analyser)

    const mute = audioCtx.createGain()
    mute.gain.value = 0
    source.connect(mute)
    mute.connect(audioCtx.destination)

    startVolumeMeter(analyser)
  }

  async function acquireMediaStream(
    audioSource: string,
    noiseSuppression: boolean,
  ): Promise<AcquiredMedia> {
    let mediaStream: MediaStream | undefined
    let warning: string | null = null
    const hasMic = audioSource.includes('mic')
    const hasSystem = audioSource.includes('system')
    const micConstraints = {
      audio: {
        echoCancellation: noiseSuppression,
        noiseSuppression: noiseSuppression,
        autoGainControl: noiseSuppression,
      }
    }
    const sysConstraints = {
      video: true,
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        ...({ suppressLocalAudioPlayback: false } as any),
      },
    } as MediaStreamConstraints

    if (hasMic && hasSystem) {
      let micStream: MediaStream | null = null
      let micFailed = false
      try {
        micStream = await navigator.mediaDevices.getUserMedia(micConstraints)
      } catch (micErr) {
        micFailed = true
        try {
          const ds = await navigator.mediaDevices.getDisplayMedia(sysConstraints)
          const sysStream = new MediaStream(ds.getAudioTracks())
          ds.getVideoTracks().forEach(t => t.stop())
          mediaStream = sysStream
          warning = '麦克风不可用，已切换为仅录制系统音频'
        } catch (sysErr: any) {
          throw new Error(
            `麦克风: ${(micErr as any)?.message || micErr}; ` +
            `系统音频: ${sysErr?.message || sysErr}`
          )
        }
      }
      if (!micFailed && micStream) {
        try {
          const ds = await navigator.mediaDevices.getDisplayMedia(sysConstraints)
          const sysStream = new MediaStream(ds.getAudioTracks())
          ds.getVideoTracks().forEach(t => t.stop())
          const ctx = new AudioContext()
          const dest = ctx.createMediaStreamDestination()
          ctx.createMediaStreamSource(micStream).connect(dest)
          ctx.createMediaStreamSource(sysStream).connect(dest)
          mergeCtx = ctx
          mediaStream = dest.stream
        } catch {
          mediaStream = micStream
          warning = '系统音频不可用，已切换为仅录制麦克风'
        }
      }
    } else if (hasSystem) {
      const ds = await navigator.mediaDevices.getDisplayMedia(sysConstraints)
      mediaStream = new MediaStream(ds.getAudioTracks())
      ds.getVideoTracks().forEach(t => t.stop())
    } else {
      mediaStream = await navigator.mediaDevices.getUserMedia(micConstraints)
    }

    stream = mediaStream ?? null
    return { stream: mediaStream, warning }
  }

  function teardownGraph() {
    if (animFrame) { cancelAnimationFrame(animFrame); animFrame = null }
    if (workletNode) { workletNode.disconnect(); workletNode = null }
    workletNode = null
    if (analyser) { analyser.disconnect(); analyser = null }
    analyser = null
    if (audioCtx) { audioCtx.close(); audioCtx = null }
    audioCtx = null
  }

  function teardownTracks() {
    if (mergeCtx) { mergeCtx.close().catch(() => {}); mergeCtx = null }
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null }
  }

  return {
    acquireMediaStream,
    startStreaming,
    startVolumeOnly,
    teardownGraph,
    teardownTracks,
    getStream: () => stream,
    getSampleRate: () => audioCtx?.sampleRate || 0,
    setOnVolume: (fn: (level: number) => void) => { onVolume = fn },
  }
}
