<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

type RecordState = 'idle' | 'preparing' | 'recording' | 'stopping' | 'cancelling' | 'done'

const state = ref<RecordState>('idle')
const taskId = ref('')
const error = ref('')
const timer = ref('00:00')
const volume = ref(0)
const elapsedSec = ref(0)

let ws: WebSocket | null = null
let startTime = 0
let timerInterval: number | null = null
let audioCtx: AudioContext | null = null
let analyser: AnalyserNode | null = null
let scriptProcessor: ScriptProcessorNode | null = null
let animFrame: number | null = null
let wsTimeout: number | null = null
let stream: MediaStream | null = null
let cancelled = false
let pendingStream: MediaStream | null = null

function formatTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

function genTaskId(): string {
  const buf = new Uint8Array(8)
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(buf)
  } else {
    for (let i = 0; i < buf.length; i++) buf[i] = Math.floor(Math.random() * 256)
  }
  return Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 12)
}

function setupAudioPipeline(s: MediaStream) {
  audioCtx = new AudioContext()
  const source = audioCtx.createMediaStreamSource(s)

  analyser = audioCtx.createAnalyser()
  analyser.fftSize = 256
  source.connect(analyser)

  scriptProcessor = audioCtx.createScriptProcessor(4096, 1, 1)
  source.connect(scriptProcessor)

  const mute = audioCtx.createGain()
  mute.gain.value = 0
  scriptProcessor.connect(mute)
  mute.connect(audioCtx.destination)

  const dataArray = new Uint8Array(analyser.frequencyBinCount)
  function tick() {
    if (!analyser) return
    analyser.getByteFrequencyData(dataArray)
    const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length
    volume.value = Math.min(avg / 160, 1)
    animFrame = requestAnimationFrame(tick)
  }
  tick()

  scriptProcessor.onaudioprocess = (e) => {
    if (ws?.readyState !== WebSocket.OPEN) return
    const f32 = e.inputBuffer.getChannelData(0)
    const i16 = new Int16Array(f32.length)
    for (let i = 0; i < f32.length; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]))
      i16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
    }
    ws.send(i16.buffer)
  }
}

function teardownAudioPipeline() {
  if (animFrame) cancelAnimationFrame(animFrame)
  animFrame = null
  if (scriptProcessor) {
    scriptProcessor.disconnect()
    scriptProcessor.onaudioprocess = null
    scriptProcessor = null
  }
  if (analyser) { analyser.disconnect(); analyser = null }
  if (audioCtx) { audioCtx.close(); audioCtx = null }
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null }
  if (pendingStream) { pendingStream.getTracks().forEach(t => t.stop()); pendingStream = null }
  volume.value = 0
}

function clearTimers() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
  if (wsTimeout) { clearTimeout(wsTimeout); wsTimeout = null }
}

function closeWs() {
  if (!ws) return
  try { ws.close() } catch {}
  ws = null
}

function resetAll() {
  clearTimers()
  closeWs()
  teardownAudioPipeline()
  cancelled = false
}

function startTimer() {
  startTime = Date.now()
  elapsedSec.value = 0
  timerInterval = window.setInterval(() => {
    elapsedSec.value = Math.floor((Date.now() - startTime) / 1000)
    timer.value = formatTime(elapsedSec.value)
  }, 200)
}

function attachLifetimeHandlers() {
  if (!ws) return
  ws.onmessage = async (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.status === 'done') {
        clearTimers()
        teardownAudioPipeline()
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

async function startRecording() {
  error.value = ''
  state.value = 'preparing'
  cancelled = false

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
    cancelled = true
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ action: 'discard' })) } catch {}
    }
    closeWs()
    clearTimers()
    state.value = 'idle'
    error.value = '无法访问麦克风: ' + (e.message || e)
    return
  }

  if (cancelled) {
    mediaStream.getTracks().forEach(t => t.stop())
    return
  }

  pendingStream = mediaStream

  try {
    if (ws && ws.readyState !== WebSocket.OPEN) {
      await openPromise
    }
  } catch (e: any) {
    pendingStream = null
    mediaStream.getTracks().forEach(t => t.stop())
    closeWs()
    clearTimers()
    state.value = 'idle'
    error.value = e.message === 'ws_timeout'
      ? '连接服务器超时'
      : '无法连接服务器，请确认后端已启动'
    return
  }

  if (cancelled) {
    if (pendingStream) {
      pendingStream.getTracks().forEach(t => t.stop())
      pendingStream = null
    }
    return
  }

  clearTimers()

  stream = mediaStream
  pendingStream = null
  setupAudioPipeline(stream)

  if (audioCtx && ws) {
    try {
      ws.send(JSON.stringify({ type: 'config', sample_rate: audioCtx.sampleRate }))
    } catch {}
  }

  attachLifetimeHandlers()

  state.value = 'recording'
  startTimer()
}

async function stopRecording() {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    state.value = 'idle'
    error.value = '连接已断开'
    resetAll()
    return
  }
  state.value = 'stopping'
  if (timerInterval) clearInterval(timerInterval)
  timerInterval = null
  teardownAudioPipeline()
  try {
    ws.send(JSON.stringify({ action: 'stop' }))
  } catch {
    state.value = 'idle'
    error.value = '发送停止指令失败'
    resetAll()
  }
}

function cancelRecording() {
  if (state.value === 'idle' || state.value === 'done' || state.value === 'cancelling') return
  cancelled = true
  state.value = 'cancelling'
  if (timerInterval) clearInterval(timerInterval)
  timerInterval = null
  if (wsTimeout) { clearTimeout(wsTimeout); wsTimeout = null }
  teardownAudioPipeline()
  if (ws) {
    if (ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ action: 'discard' })) } catch {}
    }
    try { ws.close() } catch {}
    ws = null
  }
  setTimeout(() => {
    if (state.value === 'cancelling') {
      state.value = 'idle'
    }
  }, 400)
}

onUnmounted(() => {
  resetAll()
})
</script>

<template>
  <div class="page">
    <h1>实时录音</h1>
    <p class="subtitle">使用浏览器麦克风录制会议音频</p>

    <div class="record-area">
      <div v-if="state === 'idle'" class="idle-hint">
        <div class="mic-icon">🎤</div>
        <div>点击下方按钮开始录音</div>
        <div class="idle-sub">录制完成后将自动生成转录和会议纪要</div>
      </div>

      <div v-if="state === 'preparing'" class="connecting-hint">
        <span class="spinner"></span>
        <span>正在准备...</span>
        <span class="hint-sub">打开麦克风并连接服务器</span>
      </div>

      <div v-if="state === 'recording' || state === 'stopping'" class="recording-panel">
        <div class="timer-main">{{ timer }}</div>

        <div class="volume-bars">
          <div
            v-for="i in 32" :key="i"
            class="vol-bar"
            :class="{ active: volume > (i - 1) / 32 }"
            :style="{ height: Math.max(4, 8 + Math.sin(i * 0.5) * 12 + volume * 18) + 'px' }"
          ></div>
        </div>

        <div class="recording-indicator">
          <span class="rec-dot" :class="{ stopping: state === 'stopping' }"></span>
          {{ state === 'stopping' ? '正在保存...' : '录制中' }}
        </div>
      </div>

      <div v-if="state === 'cancelling'" class="connecting-hint">
        <span class="spinner"></span>
        <span>已放弃本次录音</span>
      </div>

      <div v-if="state === 'done'" class="done-hint">
        <div class="done-icon">✓</div>
        <div>录制完成，正在跳转...</div>
      </div>

      <div class="button-row" :class="{ wrap: state !== 'idle' }">
        <button
          v-if="state === 'idle'"
          class="btn-record idle"
          @click="startRecording"
        >
          <span class="btn-icon">●</span>
          <span>开始录音</span>
        </button>

        <template v-else-if="state !== 'done' && state !== 'cancelling'">
          <button
            v-if="state === 'preparing'"
            class="btn-record preparing"
            disabled
          >
            <span class="spinner small"></span>
            <span>准备中...</span>
          </button>

          <button
            v-else-if="state === 'recording'"
            class="btn-record recording"
            @click="stopRecording"
          >
            <span class="btn-icon">■</span>
            <span>停止录音</span>
          </button>

          <button
            v-else-if="state === 'stopping'"
            class="btn-record stopping"
            disabled
          >
            <span class="spinner small"></span>
            <span>保存中...</span>
          </button>

          <button
            class="btn-cancel"
            :disabled="state === 'stopping'"
            @click="cancelRecording"
          >
            取消
          </button>
        </template>
      </div>

      <div v-if="error" class="error-box" @click="error = ''">{{ error }}</div>

      <p v-if="state === 'idle'" class="cancel-tip">
        录音中可随时点「取消」放弃本次录制，不会保存到历史任务。
      </p>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 600px; margin: 0 auto; text-align: center; }
h1 { font-size: 24px; margin-bottom: 8px; }
.subtitle { color: #888; font-size: 14px; margin-bottom: 24px; }

.record-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
  padding: 40px 32px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  min-height: 320px;
  justify-content: center;
}

.idle-hint { color: #666; font-size: 15px; }
.mic-icon { font-size: 40px; margin-bottom: 12px; }
.idle-sub { font-size: 12px; color: #aaa; margin-top: 8px; }

.connecting-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: #1a73e8;
  font-size: 14px;
}
.hint-sub { font-size: 12px; color: #999; }
.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #e0e0e0;
  border-top-color: #1a73e8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.spinner.small {
  width: 14px;
  height: 14px;
  border-width: 2px;
  display: inline-block;
  vertical-align: middle;
  margin-right: 6px;
}
@keyframes spin { to { transform: rotate(360deg); } }

.recording-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  width: 100%;
}

.timer-main {
  font-size: 56px;
  font-weight: 700;
  color: #d93025;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  letter-spacing: 3px;
}

.volume-bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 44px;
  width: 100%;
  justify-content: center;
  padding: 0 16px;
}

.vol-bar {
  flex: 1;
  max-width: 6px;
  min-height: 4px;
  border-radius: 2px;
  background: #d93025;
  opacity: 0.2;
  transition: height 0.08s ease, opacity 0.08s ease;
}
.vol-bar.active { opacity: 1; }

.recording-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #d93025;
  font-weight: 500;
}
.rec-dot {
  width: 10px;
  height: 10px;
  background: #d93025;
  border-radius: 50%;
  animation: blink 1s infinite;
}
.rec-dot.stopping { animation: none; opacity: 0.5; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }

.done-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #137333;
  font-size: 14px;
}
.done-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #137333;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  margin-bottom: 8px;
}

.button-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  width: 100%;
  max-width: 420px;
}
.button-row.wrap { flex-wrap: wrap; }

.btn-record, .btn-cancel {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px 28px;
  border: none;
  border-radius: 50px;
  font-size: 15px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-record { background: #1a73e8; color: white; min-width: 200px; }
.btn-record.idle:hover { background: #1557b0; }
.btn-record.preparing, .btn-record.stopping { background: #9aa0a6; cursor: not-allowed; }
.btn-record.recording { background: #d93025; }
.btn-record.recording:hover { background: #b71c1c; }
.btn-icon { font-size: 14px; line-height: 1; }

.btn-cancel {
  background: white;
  color: #666;
  border: 1px solid #ddd;
  min-width: 100px;
  padding: 15px 24px;
}
.btn-cancel:hover:not(:disabled) {
  border-color: #d93025;
  color: #d93025;
  background: #fff5f5;
}
.btn-cancel:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.cancel-tip {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
  max-width: 320px;
  line-height: 1.5;
}

.error-box {
  padding: 10px 14px;
  background: #fce8e6;
  border-radius: 8px;
  color: #d93025;
  font-size: 13px;
  cursor: pointer;
  max-width: 100%;
}
</style>
