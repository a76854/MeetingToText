<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const recording = ref(false)
const recorded = ref(false)
const taskId = ref('')
const error = ref('')
const timer = ref('00:00')
const errorTimerRef = ref(0)

let mediaRecorder: MediaRecorder | null = null
let ws: WebSocket | null = null
let startTime = 0
let timerInterval: number | null = null

async function startRecording() {
  error.value = ''
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })
  } catch {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRecorder = new MediaRecorder(stream)
  }

  const baseUrl = window.location.protocol === 'https:' ? `wss://${window.location.host}` : `ws://${window.location.host}`
  const res = await fetch(`/api/record/start`, { method: 'POST' })
  const data = await res.json()
  taskId.value = data.task_id

  ws = new WebSocket(`${baseUrl}/api/record/${data.task_id}`)
  ws.onopen = () => {
    recording.value = true
    startTime = Date.now()
    timerInterval = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - startTime) / 1000)
      const m = String(Math.floor(elapsed / 60)).padStart(2, '0')
      const s = String(elapsed % 60).padStart(2, '0')
      timer.value = `${m}:${s}`
    }, 1000)
  }

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)
    if (msg.status === 'done') {
      recorded.value = true
      recording.value = false
      if (timerInterval) clearInterval(timerInterval)
      router.push(`/transcript/${msg.task_id}`)
    } else if (msg.status === 'error') {
      error.value = msg.message
    }
  }

  ws.onerror = () => { error.value = 'WebSocket 连接失败' }
  ws.onclose = () => { recording.value = false; if (timerInterval) clearInterval(timerInterval) }

  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0 && ws?.readyState === WebSocket.OPEN) {
      ws.send(e.data)
    }
  }

  mediaRecorder.start(1000)
}

async function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
    mediaRecorder.stream.getTracks().forEach(t => t.stop())
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'stop' }))
    ws.close()
  }
  recording.value = false
  if (timerInterval) clearInterval(timerInterval)
}

onUnmounted(() => {
  stopRecording()
})
</script>

<template>
  <div class="page">
    <h1>实时录音</h1>
    <p class="subtitle">使用浏览器麦克风录制会议音频</p>

    <div class="record-area">
      <div class="timer" v-if="recording">{{ timer }}</div>
      <div class="status-text" v-if="!recording && !recorded">点击下方按钮开始录音</div>
      <div class="status-text processing" v-if="recorded && !recording">处理中...</div>

      <button class="btn-record" :class="{ recording }" @click="recording ? stopRecording() : startRecording()" :disabled="recorded">
        <span class="btn-icon">{{ recording ? '■' : '●' }}</span>
        {{ recording ? '停止录音' : (recorded ? '已提交' : '开始录音') }}
      </button>

      <div v-if="error" class="error-box">{{ error }}</div>
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
  padding: 40px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.timer { font-size: 48px; font-weight: 700; color: #d93025; font-variant-numeric: tabular-nums; }
.status-text { font-size: 16px; color: #666; }
.status-text.processing { color: #1a73e8; }

.btn-record {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 32px;
  border: none;
  border-radius: 50px;
  background: #1a73e8;
  color: white;
  font-size: 16px;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-record:hover { background: #1557b0; }
.btn-record.recording { background: #d93025; animation: pulse 1.5s infinite; }
.btn-record:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-icon { font-size: 18px; }

@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.05); } }

.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; }
</style>
