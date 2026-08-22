import { ref } from 'vue'
import { api } from '../api/client'

type RecorderState = 'idle' | 'preparing' | 'recording' | 'stopping' | 'cancelling' | 'done'

export const state = ref<RecorderState>('idle')
export const taskId = ref('')
export const error = ref('')
export const timer = ref('00:00')
export const volume = ref(0)
const elapsedSec = ref(0)
export const streamingAsrEnabled = ref(false)
export const noiseSuppression = ref(true)
export const audioSource = ref('mic')
export const liveText = ref('')
export const liveStatus = ref<'idle' | 'waiting' | 'active' | 'error'>('idle')
export const liveError = ref('')
export const warning = ref('')

let ws: WebSocket | null = null
let audioCtx: AudioContext | null = null
let analyser: AnalyserNode | null = null
let workletNode: AudioWorkletNode | null = null
let animFrame: number | null = null
let stream: MediaStream | null = null
let mergeCtx: AudioContext | null = null
let startTime = 0
let timerInterval: number | null = null
let wsTimeout: number | null = null
let wakeLockSentinel: any = null
let beforeUnloadHandler: ((e: BeforeUnloadEvent) => void) | null = null
let mediaRecorder: MediaRecorder | null = null
let recordedChunks: Blob[] = []
let localMode = false

function genTaskId(): string {
  const buf = new Uint8Array(8)
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(buf)
  } else {
    for (let i = 0; i < buf.length; i++) buf[i] = Math.floor(Math.random() * 256)
  }
  return Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 12)
}

function formatTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

function startTimer() {
  startTime = Date.now()
  elapsedSec.value = 0
  timer.value = '00:00'
  timerInterval = window.setInterval(() => {
    elapsedSec.value = Math.floor((Date.now() - startTime) / 1000)
    timer.value = formatTime(elapsedSec.value)
  }, 200)
}

function stopTimer() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
}

async function acquireWakeLock() {
  try {
    if ('wakeLock' in navigator) {
      wakeLockSentinel = await (navigator as any).wakeLock.request('screen')
      wakeLockSentinel?.addEventListener?.('release', () => { wakeLockSentinel = null })
    }
  } catch { /* not available or denied */ }
}

async function releaseWakeLock() {
  try { await wakeLockSentinel?.release?.() } catch {}
  wakeLockSentinel = null
}

async function setupAudioWorklet(s: MediaStream) {
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
    if (localMode || ws?.readyState !== WebSocket.OPEN) return
    const f32 = e.data as Float32Array
    const i16 = new Int16Array(f32.length)
    for (let i = 0; i < f32.length; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]))
      i16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
    }
    ws.send(i16.buffer)
  }

  startVolumeMeter(analyser)
}

function setupVolumeOnly(s: MediaStream) {
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

function startVolumeMeter(an: AnalyserNode) {
  const dataArray = new Uint8Array(an.frequencyBinCount)
  function tick() {
    if (!analyser) return
    an.getByteFrequencyData(dataArray)
    const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length
    volume.value = Math.min(avg / 160, 1)
    animFrame = requestAnimationFrame(tick)
  }
  tick()
}

function setupLocalRecorder(s: MediaStream) {
  const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : 'audio/webm'
  mediaRecorder = new MediaRecorder(s, { mimeType: mime })
  recordedChunks = []
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) recordedChunks.push(e.data)
  }
  mediaRecorder.start(1000)
}

function teardownAudioGraph() {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    mediaRecorder.stop()
  }
  mediaRecorder = null
  if (animFrame) { cancelAnimationFrame(animFrame); animFrame = null }
  if (workletNode) { workletNode.disconnect(); workletNode = null }
  workletNode = null
  if (analyser) { analyser.disconnect(); analyser = null }
  analyser = null
  if (audioCtx) { audioCtx.close(); audioCtx = null }
  audioCtx = null
  volume.value = 0
}

function teardownAudio() {
  teardownAudioGraph()
  if (mergeCtx) { mergeCtx.close().catch(() => {}); mergeCtx = null }
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null }
}

function closeWs() {
  if (!ws) return
  try { ws.close() } catch {}
  ws = null
}

function clearTimeouts() {
  if (wsTimeout) { clearTimeout(wsTimeout); wsTimeout = null }
}

function resetAll() {
  stopTimer()
  clearTimeouts()
  closeWs()
  teardownAudio()
  releaseWakeLock()
  localMode = false
  recordedChunks = []
  if (beforeUnloadHandler) {
    window.removeEventListener('beforeunload', beforeUnloadHandler)
    beforeUnloadHandler = null
  }
  liveText.value = ''
  liveStatus.value = 'idle'
  liveError.value = ''
  warning.value = ''
}

function attachWsHandlers(router: any) {
  if (!ws) return
  ws.onmessage = async (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'partial') {
        liveStatus.value = 'active'
        if (msg.text) {
          liveText.value = (liveText.value ? liveText.value + ' ' : '') + msg.text.trim()
        }
        if (msg.final) {
          liveStatus.value = 'idle'
        }
      } else if (msg.status === 'done') {
        resetAll()
        state.value = 'done'
        if (msg.task_id) {
          await new Promise(r => setTimeout(r, 500))
          router.push(`/transcript/${msg.task_id}`)
        }
        state.value = 'idle'
      } else if (msg.status === 'error') {
        state.value = 'idle'
        error.value = msg.message || '服务器处理失败'
        resetAll()
      }
    } catch {}
  }
  ws.onclose = () => {
    if (state.value === 'recording' || state.value === 'stopping') {
      if (!localMode && stream) {
        localMode = true
        setupLocalRecorder(stream)
      }
    }
  }
  ws.onerror = () => {
    if (state.value === 'recording' && !localMode && stream) {
      localMode = true
      setupLocalRecorder(stream)
    }
  }
}

export async function startRecording(router: any) {
  if (state.value !== 'idle') return

  error.value = ''
  state.value = 'preparing'
  liveText.value = ''
  liveStatus.value = streamingAsrEnabled.value ? 'waiting' : 'idle'
  liveError.value = ''

  const newTaskId = genTaskId()
  taskId.value = newTaskId

  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${proto}//${window.location.host}/api/record/${newTaskId}`

  ws = new WebSocket(wsUrl)
  ws.binaryType = 'arraybuffer'

  let openResolve!: () => void
  let openReject!: (e: Error) => void
  const openPromise = new Promise<void>((resolve, reject) => {
    openResolve = resolve
    openReject = reject
  })

  ws.onopen = () => openResolve()
  ws.onerror = () => openReject(new Error('ws_error'))

  wsTimeout = window.setTimeout(() => {
    if (state.value === 'preparing') {
      openReject(new Error('ws_timeout'))
    }
  }, 10000)

  let mediaStream: MediaStream | undefined
  warning.value = ''
  try {
    const hasMic = audioSource.value.includes('mic')
    const hasSystem = audioSource.value.includes('system')
    const micConstraints = {
      audio: {
        echoCancellation: noiseSuppression.value,
        noiseSuppression: noiseSuppression.value,
        autoGainControl: noiseSuppression.value,
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
          warning.value = '麦克风不可用，已切换为仅录制系统音频'
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
        } catch (sysErr) {
          mediaStream = micStream
          warning.value = '系统音频不可用，已切换为仅录制麦克风'
        }
      }
    } else if (hasSystem) {
      const ds = await navigator.mediaDevices.getDisplayMedia(sysConstraints)
      mediaStream = new MediaStream(ds.getAudioTracks())
      ds.getVideoTracks().forEach(t => t.stop())
    } else {
      mediaStream = await navigator.mediaDevices.getUserMedia(micConstraints)
    }
  } catch (e: any) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ action: 'discard' })) } catch {}
    }
    closeWs()
    clearTimeouts()
    state.value = 'idle'
    const label = audioSource.value.includes('system') ? '无法访问麦克风/系统音频: ' : '无法访问麦克风: '
    error.value = label + (e.message || e)
    return
  }

  if (!mediaStream) {
    state.value = 'idle'
    error.value = '无法获取任何音频源'
    return
  }

  try {
    if (ws && ws.readyState !== WebSocket.OPEN) {
      await openPromise
    }
    clearTimeouts()
    attachWsHandlers(router)
  } catch (e: any) {
    clearTimeouts()
    closeWs()
    localMode = true
  }

  stream = mediaStream

  if (!localMode) {
    try {
      await setupAudioWorklet(stream)
    } catch (e) {
      teardownAudioGraph()
      closeWs()
      localMode = true
    }
  }

  if (localMode) {
    setupVolumeOnly(mediaStream)
    setupLocalRecorder(mediaStream)
    liveStatus.value = 'idle'
  }

  if (!localMode && audioCtx && ws) {
    try {
      ws.send(JSON.stringify({ type: 'config', sample_rate: audioCtx.sampleRate }))
    } catch {}
  }

  await acquireWakeLock()

  beforeUnloadHandler = (e: BeforeUnloadEvent) => {
    e.preventDefault()
    e.returnValue = ''
  }
  window.addEventListener('beforeunload', beforeUnloadHandler)

  state.value = 'recording'
  startTimer()
}

export async function stopRecording(router?: any) {
  if (localMode) {
    state.value = 'stopping'
    stopTimer()
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.requestData()
      await new Promise(r => setTimeout(r, 300))
    }
    teardownAudio()
    const blob = new Blob(recordedChunks, { type: 'audio/webm' })
    if (blob.size > 0) {
      try {
        const file = new File([blob], `recording_${taskId.value}.webm`, { type: 'audio/webm' })
        const res = await api.upload(file)
        state.value = 'done'
        if (router) {
          await new Promise(r => setTimeout(r, 500))
          router.push(`/transcript/${res.task_id}`)
        }
        state.value = 'idle'
        releaseWakeLock()
        return
      } catch (e: any) {
        error.value = '上传录音失败，已保存到本地下载'
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `recording_${taskId.value}.webm`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        state.value = 'idle'
        releaseWakeLock()
        return
      }
    } else {
      error.value = '录音内容为空'
    }
    releaseWakeLock()
    state.value = 'idle'
    return
  }

  if (!ws || ws.readyState !== WebSocket.OPEN) {
    state.value = 'idle'
    error.value = '连接已断开'
    resetAll()
    return
  }
  state.value = 'stopping'
  stopTimer()
  teardownAudio()
  try {
    ws.send(JSON.stringify({ action: 'stop' }))
  } catch {
    state.value = 'idle'
    error.value = '发送停止指令失败'
    resetAll()
  }
}

export function cancelRecording() {
  if (state.value === 'idle' || state.value === 'done' || state.value === 'cancelling') return
  state.value = 'cancelling'
  stopTimer()
  clearTimeouts()
  teardownAudio()
  if (ws) {
    if (ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ action: 'discard' })) } catch {}
    }
    try { ws.close() } catch {}
    ws = null
  }
  releaseWakeLock()
  setTimeout(() => {
    if (state.value === 'cancelling') {
      state.value = 'idle'
    }
  }, 400)
}

export async function loadSettings() {
  try {
    const s = await api.getSettings()
    streamingAsrEnabled.value = s.streaming_asr_enabled
    noiseSuppression.value = s.browser_noise_suppression
    audioSource.value = s.audio_source || 'mic'
  } catch {
    streamingAsrEnabled.value = false
    noiseSuppression.value = true
    audioSource.value = 'mic'
  }
}

export async function toggleStreamingAsr(enabled: boolean) {
  streamingAsrEnabled.value = enabled
  try {
    await api.updateSettings({ streaming_asr_enabled: enabled })
  } catch {
    streamingAsrEnabled.value = !enabled
  }
}
