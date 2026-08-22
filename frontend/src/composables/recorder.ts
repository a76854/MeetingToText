import { ref } from 'vue'
import { api } from '../api/client'
import { formatDuration } from '../utils/format'
import { downloadBlob } from '../utils/download'

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
export const liveStatus = ref<'idle' | 'waiting' | 'active' | 'error' | 'reconnecting'>('idle')
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

// --- reconnect-resume (task-25/26) ---
// Mid-recording disconnects no longer fall back to full localMode. Instead a gap
// MediaRecorder captures the outage locally while a backoff loop reopens
// /api/record/{task_id}; on reopen the server adopts the suspended session
// ({"status":"resumed"}) and PCM streaming resumes. The retained gap blob is
// uploaded as a SECOND task at stop (recording_{task_id}_gap.webm) — zero loss.
let sampleRate = 0                       // captured once per session; re-sent as config after reconnect
let reconnectTimer: number | null = null // pending backoff attempt
let reconnectAttempt = 0                 // exponential backoff counter
let reconnectStartedAt = 0               // Date.now() of first drop; drives give-up deadline
let reconnecting = false                 // between first drop and successful reopen / give-up
let probeSock: WebSocket | null = null   // in-flight reconnect socket (pre-open)
let heartbeatInterval: number | null = null
let gapRecorder: MediaRecorder | null = null
let gapChunks: Blob[] = []
let gapBlob: Blob | null = null          // retained outage audio; second task at stop

const HEARTBEAT_MS = 10_000              // server liveness death = 3x grace; ping keeps it alive
const RECONNECT_BASE_MS = 1000           // backoff: 1s -> 2s -> 4s ... capped at 5s
const RECONNECT_MAX_MS = 5000
// Matches the backend default reconnect_grace_seconds: past this the server has
// finalized the suspended wav, so adopting would silently split the recording.
const RECONNECT_GIVE_UP_MS = 60_000
const STOP_DELIVER_TIMEOUT_MS = 3000     // bounded single-shot reconnect used when stopping mid-outage

function genTaskId(): string {
  const buf = new Uint8Array(8)
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(buf)
  } else {
    for (let i = 0; i < buf.length; i++) buf[i] = Math.floor(Math.random() * 256)
  }
  return Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 12)
}

function wsUrl(id: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api/record/${id}`
}

function startTimer() {
  startTime = Date.now()
  elapsedSec.value = 0
  timer.value = '00:00'
  timerInterval = window.setInterval(() => {
    elapsedSec.value = Math.floor((Date.now() - startTime) / 1000)
    timer.value = formatDuration(elapsedSec.value)
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

function pickWebmMime(): string {
  return MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : 'audio/webm'
}

function setupLocalRecorder(s: MediaStream) {
  mediaRecorder = new MediaRecorder(s, { mimeType: pickWebmMime() })
  recordedChunks = []
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) recordedChunks.push(e.data)
  }
  mediaRecorder.start(1000)
}

// --- heartbeat: {"type":"ping"} every 10s while the WS is open ---

function startHeartbeat() {
  stopHeartbeat()
  heartbeatInterval = window.setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: 'ping' })) } catch {}
    }
  }, HEARTBEAT_MS)
}

function stopHeartbeat() {
  if (heartbeatInterval) { clearInterval(heartbeatInterval); heartbeatInterval = null }
}

// --- gap capture: local MediaRecorder covering the outage window ---

function startGapRecorder() {
  if (gapRecorder || !stream) return
  try {
    gapChunks = []
    gapRecorder = new MediaRecorder(stream, { mimeType: pickWebmMime() })
    gapRecorder.ondataavailable = (e) => {
      if (gapRecorder && e.data.size > 0) gapChunks.push(e.data)
    }
    gapRecorder.start(1000)
  } catch { gapRecorder = null }
}

// Stop the gap recorder and RETAIN its audio: appended to gapBlob so repeated
// outages in one session accumulate into one blob.
async function finalizeGapCapture(): Promise<void> {
  const rec = gapRecorder
  if (!rec) return
  gapRecorder = null
  if (rec.state === 'recording') {
    try { rec.requestData() } catch {}
    await new Promise(r => setTimeout(r, 300))
    try { rec.stop() } catch {}
  }
  if (gapChunks.length > 0) {
    const part = new Blob(gapChunks, { type: 'audio/webm' })
    gapBlob = gapBlob ? new Blob([gapBlob, part], { type: 'audio/webm' }) : part
  }
  gapChunks = []
}

function discardGap() {
  if (gapRecorder && gapRecorder.state !== 'inactive') {
    try { gapRecorder.stop() } catch {}
  }
  gapRecorder = null
  gapChunks = []
  gapBlob = null
}

// --- reconnect loop: exponential backoff until reopen or grace-expiry give-up ---

function cancelReconnectLoop() {
  if (reconnectTimer !== null) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (probeSock && probeSock.readyState !== WebSocket.OPEN) {
    try { probeSock.close() } catch {}
  }
  probeSock = null
  reconnecting = false
  reconnectStartedAt = 0
  reconnectAttempt = 0
}

function scheduleReconnect(router: any) {
  if (reconnectTimer !== null) return
  if (Date.now() - reconnectStartedAt >= RECONNECT_GIVE_UP_MS) {
    giveUpReconnect()
    return
  }
  const delay = Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempt, RECONNECT_MAX_MS)
  reconnectAttempt++
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    if (state.value === 'recording') tryReconnect(router)
  }, delay)
}

function giveUpReconnect() {
  cancelReconnectLoop()
  // Grace clearly expired server-side: adopting would split the recording.
  // Keep the gap recorder running as plain local capture; stopRecording routes
  // to the gap-upload path via the closed-WS branch.
  liveStatus.value = 'error'
  liveError.value = '重连失败，已转为本地录制；停止后将保存断线期间的录音'
}

function handleConnectionLost(router: any) {
  if (state.value !== 'recording') return
  stopHeartbeat()
  ws = null
  startGapRecorder()
  if (reconnecting) {
    scheduleReconnect(router)
    return
  }
  reconnecting = true
  reconnectAttempt = 0
  reconnectStartedAt = Date.now()
  liveStatus.value = 'reconnecting'
  liveError.value = '网络已断开，正在重连…'
  scheduleReconnect(router)
}

function adoptSocket(sock: WebSocket, router: any, resume: boolean) {
  ws = sock
  probeSock = null
  attachWsHandlers(router)
  try { sock.send(JSON.stringify({ type: 'config', sample_rate: sampleRate })) } catch {}
  if (resume) {
    startHeartbeat()
    reconnecting = false
    reconnectStartedAt = 0
    reconnectAttempt = 0
    liveError.value = ''
    liveStatus.value = streamingAsrEnabled.value ? 'waiting' : 'idle'
    void finalizeGapCapture()
  } else {
    // Stopping mid-outage: hand {"action":"stop"} over now so the server
    // finalizes the pre-disconnect wav immediately; "done" (and the gap
    // upload) arrive through attachWsHandlers.
    try { sock.send(JSON.stringify({ action: 'stop' })) } catch {}
  }
}

function tryReconnect(router: any) {
  if (state.value !== 'recording') return
  let sock: WebSocket
  try { sock = new WebSocket(wsUrl(taskId.value)) } catch { scheduleReconnect(router); return }
  sock.binaryType = 'arraybuffer'
  probeSock = sock
  sock.onopen = () => {
    if (state.value === 'stopping') {
      adoptSocket(sock, router, false)
      return
    }
    if (state.value !== 'recording') {
      try { sock.close() } catch {}
      return
    }
    adoptSocket(sock, router, true)
  }
  sock.onclose = () => {
    if (probeSock === sock) probeSock = null
    handleConnectionLost(router)
  }
  sock.onerror = () => { handleConnectionLost(router) }
}

// Single bounded reconnect used by stopRecording when the WS is already down:
// resolves true once the stop intent was delivered (done/error then flow
// through attachWsHandlers), false if the server stayed unreachable.
function tryDeliverStop(router: any): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false
    const settle = (v: boolean) => { if (!settled) { settled = true; resolve(v) } }
    let sock: WebSocket
    try { sock = new WebSocket(wsUrl(taskId.value)) } catch { settle(false); return }
    sock.binaryType = 'arraybuffer'
    const failT = window.setTimeout(() => {
      if (!settled) { try { sock.close() } catch {} }
    }, STOP_DELIVER_TIMEOUT_MS)
    sock.onopen = () => {
      clearTimeout(failT)
      if (settled) { try { sock.close() } catch {}; return }
      adoptSocket(sock, router, false)
      settle(true)
    }
    sock.onclose = () => { clearTimeout(failT); settle(false) }
    sock.onerror = () => {}
  })
}

// Upload the outage-gap webm as its own task (used when the main wav cannot be
// finalized with us, e.g. stop while unreachable past every retry).
async function uploadGapTask(blob: Blob, router?: any): Promise<void> {
  const name = `recording_${taskId.value}_gap.webm`
  try {
    const res = await api.upload(new File([blob], name, { type: 'audio/webm' }))
    if (router) {
      state.value = 'done'
      await new Promise(r => setTimeout(r, 500))
      router.push(`/transcript/${res.task_id}`)
      state.value = 'idle'
    }
  } catch {
    error.value = '上传录音失败，已保存到本地下载'
    downloadBlob(name, blob)
  }
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
  cancelReconnectLoop()
  stopHeartbeat()
  closeWs()
  discardGap()
  teardownAudio()
  releaseWakeLock()
  localMode = false
  sampleRate = 0
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
      } else if (msg.status === 'resumed') {
        // Server adopted the suspended session after our reconnect.
        liveError.value = ''
        liveStatus.value = streamingAsrEnabled.value ? 'active' : 'idle'
      } else if (msg.status === 'done') {
        const mainTaskId: string = msg.task_id || ''
        const gapToUpload = gapBlob
        resetAll()
        state.value = 'done'
        let navId = mainTaskId
        if (gapToUpload && gapToUpload.size > 0) {
          // Outage audio captured locally becomes a SECOND task (zero loss);
          // navigation goes to the main wav task without waiting on it.
          const gapId = mainTaskId || taskId.value
          api.upload(new File([gapToUpload], `recording_${gapId}_gap.webm`, { type: 'audio/webm' }))
            .catch(() => { warning.value = '断线期间录音上传失败，该段未保存' })
        }
        if (navId) {
          await new Promise(r => setTimeout(r, 500))
          router.push(`/transcript/${navId}`)
        }
        state.value = 'idle'
      } else if (msg.status === 'error' && msg.code === 'session_busy') {
        // Second concurrent WS for this task. While reconnecting this is just
        // a stale owner: retry on the next backoff tick. Otherwise fatal.
        if (reconnecting) {
          try { ws?.close() } catch {}
          ws = null
        } else {
          error.value = msg.message || '录音会话被占用'
          resetAll()
          state.value = 'idle'
        }
      } else if (msg.status === 'error') {
        const gapSalvage = gapBlob
        resetAll()
        state.value = 'idle'
        if (gapSalvage && gapSalvage.size > 0) {
          warning.value = '服务器处理失败，已改为保存断线期间的本地录音'
          void uploadGapTask(gapSalvage, router)
        } else {
          error.value = msg.message || '服务器处理失败'
        }
      }
      // {"status":"discarded"} needs no client action (cancel path).
    } catch {}
  }
  ws.onclose = () => { handleConnectionLost(router) }
  ws.onerror = () => { handleConnectionLost(router) }
}

export async function startRecording(router: any) {
  if (state.value !== 'idle') return

  error.value = ''
  state.value = 'preparing'
  liveText.value = ''
  liveStatus.value = streamingAsrEnabled.value ? 'waiting' : 'idle'
  liveError.value = ''
  cancelReconnectLoop()
  stopHeartbeat()
  discardGap()

  const newTaskId = genTaskId()
  taskId.value = newTaskId

  ws = new WebSocket(wsUrl(newTaskId))
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
      sampleRate = audioCtx?.sampleRate || 0
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
    // Best-effort: finalize the server-side wav immediately on tab close
    // instead of waiting out the full reconnect grace.
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ action: 'stop' })) } catch {}
    }
    e.preventDefault()
    e.returnValue = ''
  }
  window.addEventListener('beforeunload', beforeUnloadHandler)

  if (!localMode) startHeartbeat()

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
        downloadBlob(`recording_${taskId.value}.webm`, blob)
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
    // Stop pressed during an outage: capture the gap audio, then make ONE
    // bounded reconnect attempt to deliver {"action":"stop"} so the
    // pre-disconnect wav finalizes NOW (task_id returns via "done" and the gap
    // uploads as a second task). If unreachable, upload the gap webm alone;
    // the server grace-finalizes the suspended part into its own task.
    state.value = 'stopping'
    stopTimer()
    cancelReconnectLoop()
    stopHeartbeat()
    await finalizeGapCapture()
    teardownAudio()
    releaseWakeLock()
    const delivered = await tryDeliverStop(router)
    if (!delivered) {
      const gap = gapBlob
      gapBlob = null
      if (gap && gap.size > 0) {
        await uploadGapTask(gap, router)
      } else {
        error.value = '连接已断开且无可用录音内容'
        state.value = 'idle'
      }
    }
    return
  }

  state.value = 'stopping'
  stopTimer()
  cancelReconnectLoop()
  await finalizeGapCapture()
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
  cancelReconnectLoop()
  stopHeartbeat()
  discardGap()
  teardownAudio()
  if (ws) {
    if (ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ action: 'discard' })) } catch {}
    }
    try { ws.close() } catch {}
    ws = null
  }
  // A suspended session may exist server-side after a disconnect; discard it
  // via REST so the grace timer never finalizes it into a task.
  if (taskId.value) {
    try { fetch(`/api/record/${taskId.value}`, { method: 'DELETE' }).catch(() => {}) } catch {}
  }
  if (beforeUnloadHandler) {
    window.removeEventListener('beforeunload', beforeUnloadHandler)
    beforeUnloadHandler = null
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
