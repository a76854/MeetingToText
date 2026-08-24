/**
 * Recording orchestrator — module-level singleton state + glue.
 *
 * The whole recording flow was split into three concerns (todo 18):
 *
 *   - services/wsRecorderClient.ts   WIRE: the /api/record/{task_id} socket,
 *                                    frame builders, heartbeat, reconnect
 *                                    backoff and outage gap capture. Pure TS,
 *                                    zero Vue imports; reports inbound frames
 *                                    through typed callbacks.
 *   - composables/useAudioCapture.ts MEDIA: getUserMedia/displayMedia
 *                                    acquisition, the PCM AudioWorklet graph,
 *                                    the volume meter, teardown.
 *   - this module                    ORCHESTRATION: the UI refs, timer,
 *                                    wake-lock and beforeunload guards, and
 *                                    the start/stop/cancel/settings flows
 *                                    that wire the other two together.
 *
 * This module is deliberately a global singleton: its refs are exported and
 * imported directly by RecordPage.vue, so an in-flight recording survives
 * route changes (the audio graph and the websocket live here, not inside the
 * page component's setup scope).
 */
import { ref } from 'vue'
import { api } from '../api/client'
import { formatDuration } from '../utils/format'
import { downloadBlob } from '../utils/download'
import {
  WsRecorderClient,
  pickWebmMime,
  type WsRecorderCallbacks,
  type WsRecorderHost,
} from '../services/wsRecorderClient'
import { useAudioCapture } from './useAudioCapture'

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

let startTime = 0
let timerInterval: number | null = null
let wakeLockSentinel: any = null
let beforeUnloadHandler: ((e: BeforeUnloadEvent) => void) | null = null
let mediaRecorder: MediaRecorder | null = null
let recordedChunks: Blob[] = []
let localMode = false
// Router captured at startRecording; used by the done/error callbacks the
// same way the original attachWsHandlers closure captured its router param.
let activeRouter: any = null

const capture = useAudioCapture()
capture.setOnVolume((level) => { volume.value = level })

function genTaskId(): string {
  const buf = new Uint8Array(8)
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(buf)
  } else {
    for (let i = 0; i < buf.length; i++) buf[i] = Math.floor(Math.random() * 256)
  }
  return Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 12)
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

function setupLocalRecorder(s: MediaStream) {
  mediaRecorder = new MediaRecorder(s, { mimeType: pickWebmMime() })
  recordedChunks = []
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) recordedChunks.push(e.data)
  }
  mediaRecorder.start(1000)
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
  capture.teardownGraph()
  volume.value = 0
}

function teardownAudio() {
  teardownAudioGraph()
  capture.teardownTracks()
}

function resetAll() {
  stopTimer()
  client.cancelReconnectLoop()
  client.stopHeartbeat()
  client.close()
  client.discardGap()
  teardownAudio()
  releaseWakeLock()
  localMode = false
  client.setSampleRate(0)
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

// --- transport wiring: the client asks the host for UI-state facts and
// reports every inbound wire frame back through these callbacks. ---

const host: WsRecorderHost = {
  taskId: () => taskId.value,
  isRecording: () => state.value === 'recording',
  isStopping: () => state.value === 'stopping',
  stream: () => capture.getStream(),
  resetAll: () => resetAll(),
}

const callbacks: WsRecorderCallbacks = {
  // {"type":"partial","text":..,"final":?}
  onPartial: (text, isFinal) => {
    liveStatus.value = 'active'
    if (text) {
      liveText.value = (liveText.value ? liveText.value + ' ' : '') + text.trim()
    }
    if (isFinal) {
      liveStatus.value = 'idle'
    }
  },
  // {"status":"resumed"} — server adopted the suspended session after our reconnect.
  onResumed: () => {
    liveError.value = ''
    liveStatus.value = streamingAsrEnabled.value ? 'active' : 'idle'
  },
  // {"status":"done"} — reset, upload the gap blob as a SECOND task (zero
  // loss), navigate to the main wav task without waiting on it.
  onDone: async (mainTaskId, gapToUpload) => {
    resetAll()
    state.value = 'done'
    const navId = mainTaskId
    if (gapToUpload && gapToUpload.size > 0) {
      const gapId = mainTaskId || taskId.value
      api.upload(new File([gapToUpload], `recording_${gapId}_gap.webm`, { type: 'audio/webm' }))
        .catch(() => { warning.value = '断线期间录音上传失败，该段未保存' })
    }
    if (navId) {
      await new Promise(r => setTimeout(r, 500))
      activeRouter.push(`/transcript/${navId}`)
    }
    state.value = 'idle'
  },
  // {"status":"error","code":"session_busy"} — fatal outside a reconnect
  // (the client swallows the stale-owner case itself and keeps retrying).
  onSessionBusy: (message) => {
    error.value = message || '录音会话被占用'
    resetAll()
    state.value = 'idle'
  },
  // {"status":"error"} — salvage the gap audio if any, else surface the error.
  onError: (message, gapSalvage) => {
    resetAll()
    state.value = 'idle'
    if (gapSalvage && gapSalvage.size > 0) {
      warning.value = '服务器处理失败，已改为保存断线期间的本地录音'
      void uploadGapTask(gapSalvage, activeRouter)
    } else {
      error.value = message || '服务器处理失败'
    }
  },
  // {"status":"discarded"} needs no client action (cancel path).
  onDiscarded: () => {},
  // First drop of a reconnect cycle.
  onConnectionLost: () => {
    liveStatus.value = 'reconnecting'
    liveError.value = '网络已断开，正在重连…'
  },
  // Grace clearly expired server-side: adopting would split the recording.
  // Keep the gap recorder running as plain local capture; stopRecording routes
  // to the gap-upload path via the closed-WS branch.
  onGiveUpReconnect: () => {
    liveStatus.value = 'error'
    liveError.value = '重连失败，已转为本地录制；停止后将保存断线期间的录音'
  },
  // Reconnect socket adopted; the server's resumed confirmation is next.
  onReconnectAdopted: () => {
    liveError.value = ''
    liveStatus.value = streamingAsrEnabled.value ? 'waiting' : 'idle'
  },
}

const client = new WsRecorderClient(host, callbacks)

export async function startRecording(router: any) {
  if (state.value !== 'idle') return

  activeRouter = router
  error.value = ''
  state.value = 'preparing'
  liveText.value = ''
  liveStatus.value = streamingAsrEnabled.value ? 'waiting' : 'idle'
  liveError.value = ''
  client.cancelReconnectLoop()
  client.stopHeartbeat()
  client.discardGap()

  const newTaskId = genTaskId()
  taskId.value = newTaskId

  const openPromise = client.connect(newTaskId, 10000, () => state.value === 'preparing')

  let mediaStream: MediaStream | undefined
  warning.value = ''
  try {
    const acquired = await capture.acquireMediaStream(audioSource.value, noiseSuppression.value)
    mediaStream = acquired.stream
    if (acquired.warning) warning.value = acquired.warning
  } catch (e: any) {
    if (client.isOpen()) {
      try { client.sendDiscard() } catch {}
    }
    client.close()
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
    if (client.isConnecting()) {
      await openPromise
    }
    client.attach()
  } catch (e: any) {
    client.close()
    localMode = true
  }

  if (!localMode) {
    try {
      await capture.startStreaming(mediaStream, (f32) => {
        if (!localMode) client.sendPcm(f32)
      })
      client.setSampleRate(capture.getSampleRate())
    } catch (e) {
      teardownAudioGraph()
      client.close()
      localMode = true
    }
  }

  if (localMode) {
    capture.startVolumeOnly(mediaStream)
    setupLocalRecorder(mediaStream)
    liveStatus.value = 'idle'
  }

  if (!localMode && client.isOpen()) {
    client.sendConfig(capture.getSampleRate())
  }

  await acquireWakeLock()

  beforeUnloadHandler = (e: BeforeUnloadEvent) => {
    // Best-effort: finalize the server-side wav immediately on tab close
    // instead of waiting out the full reconnect grace.
    if (client.isOpen()) {
      try { client.sendStop() } catch {}
    }
    e.preventDefault()
    e.returnValue = ''
  }
  window.addEventListener('beforeunload', beforeUnloadHandler)

  if (!localMode) client.startHeartbeat()

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

  if (!client.isOpen()) {
    // Stop pressed during an outage: capture the gap audio, then make ONE
    // bounded reconnect attempt to deliver {"action":"stop"} so the
    // pre-disconnect wav finalizes NOW (task_id returns via "done" and the gap
    // uploads as a second task). If unreachable, upload the gap webm alone;
    // the server grace-finalizes the suspended part into its own task.
    state.value = 'stopping'
    stopTimer()
    client.cancelReconnectLoop()
    client.stopHeartbeat()
    await client.finalizeGapCapture()
    teardownAudio()
    releaseWakeLock()
    const delivered = await client.tryDeliverStop()
    if (!delivered) {
      const gap = client.getGapBlob()
      client.clearGapBlob()
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
  client.cancelReconnectLoop()
  await client.finalizeGapCapture()
  teardownAudio()
  try {
    client.sendStop()
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
  client.cancelReconnectLoop()
  client.stopHeartbeat()
  client.discardGap()
  teardownAudio()
  if (client.isOpen()) {
    try { client.sendDiscard() } catch {}
  }
  client.close()
  // A suspended session may exist server-side after a disconnect; discard it
  // via REST so the grace timer never finalizes it into a task.
  // Fire-and-forget: swallow errors deliberately, cancel paths get no new error UI (todo 19).
  if (taskId.value) {
    try { api.deleteRecordingSession(taskId.value).catch(() => {}) } catch {}
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
