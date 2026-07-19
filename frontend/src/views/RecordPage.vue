<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

type RecordState = 'idle' | 'opening_mic' | 'connecting' | 'recording' | 'stopping' | 'done'

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

function formatTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

function setupAudioPipeline(s: MediaStream) {
  audioCtx = new AudioContext({ sampleRate: 16000 })
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
  volume.value = 0
}

function resetAll() {
  if (timerInterval) clearInterval(timerInterval)
  timerInterval = null
  if (wsTimeout) clearTimeout(wsTimeout)
  wsTimeout = null
  if (ws) { ws.close(); ws = null }
  teardownAudioPipeline()
}

async function startRecording() {
  error.value = ''
  state.value = 'opening_mic'

  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (e: any) {
    state.value = 'idle'
    error.value = '无法访问麦克风: ' + (e.message || e)
    return
  }

  setupAudioPipeline(stream!)
  state.value = 'connecting'

  const baseUrl = window.location.protocol === 'https:' ? `wss://${window.location.host}` : `ws://${window.location.host}`
  let data: any
  try {
    const res = await fetch(`/api/record/start`, { method: 'POST' })
    data = await res.json()
  } catch {
    state.value = 'idle'
    error.value = '无法连接服务器，请确认后端已启动'
    teardownAudioPipeline()
    return
  }

  taskId.value = data.task_id
  ws = new WebSocket(`${baseUrl}/api/record/${data.task_id}`)
  ws.binaryType = 'arraybuffer'

  wsTimeout = window.setTimeout(() => {
    if (state.value === 'connecting') {
      state.value = 'idle'
      error.value = '连接服务器超时'
      resetAll()
    }
  }, 15000)

  ws.onopen = () => {
    if (wsTimeout) clearTimeout(wsTimeout)
    wsTimeout = null
    state.value = 'recording'
    startTime = Date.now()
    elapsedSec.value = 0
    timerInterval = window.setInterval(() => {
      elapsedSec.value = Math.floor((Date.now() - startTime) / 1000)
      timer.value = formatTime(elapsedSec.value)
    }, 200)
  }

  ws.onerror = () => {
    if (state.value === 'connecting') {
      state.value = 'idle'
      error.value = 'WebSocket 连接失败'
      resetAll()
    }
  }

  ws.onclose = () => {
    if (state.value === 'recording') {
      state.value = 'idle'
      error.value = '服务器连接断开'
      resetAll()
    }
  }

  ws.onmessage = async (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.status === 'done') {
        if (timerInterval) clearInterval(timerInterval)
        state.value = 'done'
        if (msg.task_id) {
          await new Promise(r => setTimeout(r, 800))
          router.push(`/transcript/${msg.task_id}`)
        }
      } else if (msg.status === 'error') {
        state.value = 'idle'
        error.value = msg.message || '服务器处理失败'
        resetAll()
      }
    } catch {
    }
  }
}

async function stopRecording() {
  state.value = 'stopping'
  if (timerInterval) clearInterval(timerInterval)
  timerInterval = null
  teardownAudioPipeline()

  if (!ws || ws.readyState !== WebSocket.OPEN) {
    state.value = 'idle'
    error.value = '连接已断开'
    return
  }

  ws.send(JSON.stringify({ action: 'stop' }))
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

      <div v-if="state === 'opening_mic'" class="connecting-hint">
        <span class="spinner"></span>
        <span>正在打开麦克风...</span>
      </div>

      <div v-if="state === 'connecting'" class="connecting-hint">
        <span class="spinner"></span>
        <span>正在连接服务器...</span>
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

        <div class="time-axis">{{ timer }}</div>

        <div class="recording-indicator">
          <span class="rec-dot"></span>
          {{ state === 'stopping' ? '正在停止...' : '录制中' }}
        </div>
      </div>

      <div v-if="state === 'done'" class="done-hint">
        <div class="done-icon">✓</div>
        <div>录制完成，正在跳转...</div>
      </div>

      <button
        class="btn-record"
        :class="state"
        :disabled="state === 'opening_mic' || state === 'connecting' || state === 'stopping' || state === 'done'"
        @click="state === 'recording' ? stopRecording() : startRecording()"
      >
        <span class="btn-icon">{{ state === 'recording' ? '■' : '●' }}</span>
        <span v-if="state === 'idle'">开始录音</span>
        <span v-else-if="state === 'opening_mic'">打开麦克风中</span>
        <span v-else-if="state === 'connecting'">连接服务器中</span>
        <span v-else-if="state === 'recording'">停止录音</span>
        <span v-else-if="state === 'stopping'">停止中</span>
        <span v-else>已提交</span>
      </button>

      <div v-if="error" class="error-box" @click="error = ''">{{ error }}</div>
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
  gap: 14px;
  color: #1a73e8;
  font-size: 14px;
}
.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #e0e0e0;
  border-top-color: #1a73e8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
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

.time-axis {
  font-size: 12px;
  color: #aaa;
  font-variant-numeric: tabular-nums;
}

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

.btn-record {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px 32px;
  border: none;
  border-radius: 50px;
  background: #1a73e8;
  color: white;
  font-size: 16px;
  cursor: pointer;
  transition: all 0.2s;
  min-width: 180px;
}
.btn-record:hover:not(:disabled) { background: #1557b0; }
.btn-record.opening_mic,
.btn-record.connecting,
.btn-record.stopping { opacity: 0.7; cursor: not-allowed; }
.btn-record:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-record.recording { background: #d93025; }
.btn-record.recording:hover { background: #b71c1c; }
.btn-icon { font-size: 14px; }

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