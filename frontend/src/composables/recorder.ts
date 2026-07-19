import { ref } from 'vue'
import { api } from '../api/client'

export type RecorderState = 'idle' | 'preparing' | 'recording' | 'stopping' | 'cancelling' | 'done'

export const state = ref<RecorderState>('idle')
export const taskId = ref('')
export const error = ref('')
export const timer = ref('00:00')
export const volume = ref(0)
export const elapsedSec = ref(0)
export const streamingAsrEnabled = ref(false)
export const liveText = ref('')
export const liveStatus = ref<'idle' | 'waiting' | 'active' | 'error'>('idle')
export const liveError = ref('')

let ws: WebSocket | null = null
let audioCtx: AudioContext | null = null
let analyser: AnalyserNode | null = null
let workletNode: AudioWorkletNode | null = null
let animFrame: number | null = null
let stream: MediaStream | null = null
let startTime = 0
let timerInterval: number | null = null
let wsTimeout: number | null = null
let wakeLockSentinel: any = null
let beforeUnloadHandler: ((e: BeforeUnloadEvent) => void) | null = null

function genTaskId(): string {
  const buf = new Uint8Array(8)
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(buf)
  } else {
    for (let i = 0; i < buf.length; i++) buf[i] = Math.floor(Math.random() * 256)
  }
  return Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 12)
}

export function formatTime(s: number): string {
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
    if (ws?.readyState !== WebSocket.OPEN) return
    const f32 = e.data as Float32Array
    const i16 = new Int16Array(f32.length)
    for (let i = 0; i < f32.length; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]))
      i16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
    }
    ws.send(i16.buffer)
  }

  const dataArray = new Uint8Array(analyser.frequencyBinCount)
  function tick() {
    if (!analyser) return
    analyser.getByteFrequencyData(dataArray)
    const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length
    volume.value = Math.min(avg / 160, 1)
    animFrame = requestAnimationFrame(tick)
  }
  tick()
}

function teardownAudio() {
  if (animFrame) { cancelAnimationFrame(animFrame); animFrame = null }
  if (workletNode) { workletNode.disconnect(); workletNode = null }
  if (analyser) { analyser.disconnect(); analyser = null }
  if (audioCtx) { audioCtx.close(); audioCtx = null }
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null }
  volume.value = 0
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
  if (beforeUnloadHandler) {
    window.removeEventListener('beforeunload', beforeUnloadHandler)
    beforeUnloadHandler = null
  }
  liveText.value = ''
  liveStatus.value = 'idle'
  liveError.value = ''
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
      } else if (msg.status === 'error') {
        state.value = 'idle'
        error.value = msg.message || '服务器处理失败'
        resetAll()
      }
    } catch {}
  }
  ws.onclose = () => {
    if (state.value === 'recording' || state.value === 'stopping') {
      state.value = 'idle'
      error.value = '服务器连接断开'
      resetAll()
    }
  }
  ws.onerror = () => {
    if (state.value === 'recording') {
      state.value = 'idle'
      error.value = '连接出错'
      resetAll()
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

  let mediaStream: MediaStream
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (e: any) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ action: 'discard' })) } catch {}
    }
    closeWs()
    clearTimeouts()
    state.value = 'idle'
    error.value = '无法访问麦克风: ' + (e.message || e)
    return
  }

  try {
    if (ws && ws.readyState !== WebSocket.OPEN) {
      await openPromise
    }
  } catch (e: any) {
    mediaStream.getTracks().forEach(t => t.stop())
    closeWs()
    clearTimeouts()
    state.value = 'idle'
    error.value = e.message === 'ws_timeout'
      ? '连接服务器超时'
      : '无法连接服务器，请确认后端已启动'
    return
  }

  clearTimeouts()

  stream = mediaStream

  try {
    await setupAudioWorklet(stream)
  } catch (e) {
    teardownAudio()
    closeWs()
    state.value = 'idle'
    error.value = '初始化音频管线失败'
    return
  }

  if (audioCtx && ws) {
    try {
      ws.send(JSON.stringify({ type: 'config', sample_rate: audioCtx.sampleRate }))
    } catch {}
  }

  attachWsHandlers(router)

  await acquireWakeLock()

  beforeUnloadHandler = (e: BeforeUnloadEvent) => {
    e.preventDefault()
    e.returnValue = ''
  }
  window.addEventListener('beforeunload', beforeUnloadHandler)

  state.value = 'recording'
  startTimer()
}

export async function stopRecording() {
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
  } catch {
    streamingAsrEnabled.value = false
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
