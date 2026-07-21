<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import ProgressIndicator from '../components/ProgressIndicator.vue'

const route = useRoute()
const router = useRouter()

const taskId = route.params.taskId as string
const loading = ref(true)
const status = ref('')
const segments = ref<any[]>([])
const fullText = ref('')
const duration = ref(0)
const progress = ref<any>(null)
const error = ref('')
const pipelineError = ref('')
const playingId = ref<string | null>(null)
const audioCurrentTime = ref(0)
const audioDuration = ref(0)
let audioEventsAttached = false

let es: EventSource | null = null

onMounted(async () => {
  await loadTask()
  if (status.value === 'processing' || status.value === 'pending') {
    subscribeProgress()
  }
  loading.value = false
})

onUnmounted(() => {
  if (es) es.close()
})

async function loadTask() {
  try {
    const data = await api.getTranscript(taskId)
    status.value = data.status
    segments.value = (data.segments || []).map((s: any) => ({ ...s }))
    fullText.value = data.full_text
    duration.value = data.duration
    pipelineError.value = data.error || ''
  } catch (e: any) {
    error.value = e.message || '加载失败'
  }
}

function subscribeProgress() {
  es = api.streamProgress(
    taskId,
    (t) => {
      progress.value = t.progress
      status.value = t.status
    },
    (t) => {
      status.value = t.status
      segments.value = (t.result?.segments || []).map((s: any) => ({ ...s }))
      fullText.value = t.result?.full_text || ''
      duration.value = t.result?.duration || 0
      pipelineError.value = t.error || ''
      progress.value = null
    },
    (e) => {
      error.value = e
      progress.value = null
    },
  )
}

function formatTime(s: number) {
  if (!s && s !== 0) return ''
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  }
  return `${m}:${String(sec).padStart(2, '0')}`
}

function goToGenerate() {
  router.push(`/generate/${taskId}`)
}

function goToEdit() {
  router.push(`/edit/${taskId}`)
}

async function deleteTask() {
  if (!confirm('确认删除此任务？音频和转录将一并清除，不可恢复。')) return
  try {
    await api.deleteTask(taskId)
    router.push('/tasks')
  } catch (e: any) {
    error.value = e.message || '删除失败'
  }
}

function exportAs(format: string) {
  const url = api.exportUrl(taskId, format)
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function togglePlay() {
  const audio = document.getElementById('transcript-audio') as HTMLAudioElement | null
  if (!audio) return
  initAudioEvents()
  if (audio.paused) {
    audio.play().then(() => { playingId.value = 'play' }).catch(() => {})
  } else {
    audio.pause()
    playingId.value = null
  }
}

function initAudioEvents() {
  if (audioEventsAttached) return
  const audio = document.getElementById('transcript-audio') as HTMLAudioElement | null
  if (!audio) return
  if (audio.duration && isFinite(audio.duration)) {
    audioDuration.value = audio.duration
  }
  audio.addEventListener('timeupdate', () => {
    audioCurrentTime.value = audio.currentTime
  })
  audio.addEventListener('loadedmetadata', () => {
    audioDuration.value = audio.duration
  })
  audio.addEventListener('ended', () => {
    playingId.value = null
    audioCurrentTime.value = 0
  })
  audioEventsAttached = true
}

function onSeekInput(e: Event) {
  audioCurrentTime.value = parseFloat((e.target as HTMLInputElement).value)
}

function onSeekChange(e: Event) {
  const val = parseFloat((e.target as HTMLInputElement).value)
  const audio = document.getElementById('transcript-audio') as HTMLAudioElement | null
  if (!audio) return
  initAudioEvents()
  audio.currentTime = val
  audioCurrentTime.value = val
}

async function retryTranscribe() {
  if (!confirm('重新转录？当前转录结果将被覆盖。')) return
  try {
    await api.retryTranscribe(taskId)
    status.value = 'pending'
    segments.value = []
    fullText.value = ''
    progress.value = null
    subscribeProgress()
  } catch (e: any) {
    error.value = e.message || '重新转录失败'
  }
}
</script>

<template>
  <div class="page">
    <div class="header">
      <h1>转录结果</h1>
      <div class="header-actions">
        <span v-if="status === 'processing'" class="status-badge processing">转写中...</span>
        <template v-if="status === 'done'">
          <div class="audio-controls">
            <button class="btn-secondary btn-play" @click="togglePlay">{{ playingId ? '暂停' : '播放' }}</button>
            <div class="seek-row">
              <span class="seek-time">{{ formatTime(audioCurrentTime) }}</span>
              <input type="range" class="seek-slider" min="0" :max="audioDuration || 0" step="0.1" :value="audioCurrentTime" @input="onSeekInput" @change="onSeekChange" />
              <span class="seek-time">{{ formatTime(audioDuration) }}</span>
            </div>
          </div>
          <button class="btn-secondary" @click="retryTranscribe">重转</button>
          <button class="btn-secondary" @click="goToEdit">编辑</button>
        </template>
      </div>
    </div>

    <div v-if="loading" class="status-box">加载中...</div>
    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="status === 'processing' || status === 'pending'" class="processing-area">
      <ProgressIndicator v-if="progress" :progress="progress" :task="{ status }" />
      <div v-else class="status-box">正在处理转写，请稍候...</div>
    </div>

    <div v-else-if="status === 'error'" class="error-state">
      <div class="error-box">{{ pipelineError || '转写出错' }}</div>
      <div class="error-actions">
        <button class="btn-secondary" @click="retryTranscribe">重新转录</button>
        <button class="btn-delete" @click="deleteTask">删除任务</button>
      </div>
    </div>

    <div v-if="status === 'done' && !error" class="transcript-container">

      <div v-for="(seg, i) in segments" :key="i" class="segment">
          <div class="seg-meta">
            <span class="seg-speaker" :class="{ noSpeaker: !seg.speaker }">{{ seg.speaker || '未知说话人' }}</span>
            <span class="seg-time">{{ formatTime(seg.start) }} - {{ formatTime(seg.end) }}</span>
          </div>
          <div class="seg-text">{{ seg.text }}</div>
        </div>

        <div v-if="!segments.length && fullText" class="full-text">
          <pre>{{ fullText }}</pre>
        </div>

        <div v-if="!segments.length && !fullText" class="empty-hint">
          <div v-if="pipelineError" class="empty-detail">{{ pipelineError }}</div>
          <div v-else>转录完成，但未能识别到语音内容。请检查麦克风是否正常工作后重新录制。</div>
        </div>

      <div v-if="status === 'done' && (segments.length || fullText)" class="footer-actions">
        <div class="export-group">
          <span class="footer-label">导出：</span>
          <button class="btn-export" @click="exportAs('txt')">TXT</button>
          <button class="btn-export" @click="exportAs('srt')">SRT 字幕</button>
          <button class="btn-export" @click="exportAs('md')">Markdown</button>
        </div>
        <div class="footer-right">
          <button class="btn-secondary" @click="goToGenerate">生成纪要</button>
          <button class="btn-delete" @click="deleteTask">删除任务</button>
        </div>
        <audio id="transcript-audio" :src="api.audioUrl(taskId)"></audio>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 760px; margin: 0 auto; }

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}
h1 { font-size: 24px; }

.header-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.audio-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}
.btn-play { min-width: 52px; }
.seek-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.seek-time {
  font-size: 12px;
  color: #666;
  font-variant-numeric: tabular-nums;
  min-width: 36px;
}
.seek-slider {
  width: 120px;
  height: 4px;
  cursor: pointer;
  accent-color: #1a73e8;
}

.status-badge {
  font-size: 13px;
  padding: 4px 12px;
  border-radius: 20px;
  font-weight: 500;
}
.status-badge.processing { background: #fff3cd; color: #856404; }

.btn-primary, .btn-secondary, .btn-export, .btn-delete {
  font-family: inherit;
  cursor: pointer;
  border-radius: 8px;
  border: 1px solid transparent;
  transition: all 0.15s;
}
.btn-primary {
  padding: 8px 16px;
  background: #1a73e8;
  color: white;
  border-color: #1a73e8;
  font-size: 13px;
}
.btn-primary:hover:not(:disabled) { background: #1557b0; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary {
  padding: 8px 14px;
  background: white;
  color: #1a73e8;
  border-color: #1a73e8;
  font-size: 13px;
}
.btn-secondary:hover { background: #f0f6ff; }

.btn-export {
  padding: 6px 10px;
  background: white;
  color: #444;
  border-color: #ddd;
  font-size: 12px;
}
.btn-export:hover { border-color: #1a73e8; color: #1a73e8; }

.btn-delete {
  padding: 6px 12px;
  background: white;
  color: #d93025;
  border-color: #f4c2c0;
  font-size: 12px;
}
.btn-delete:hover { background: #fce8e6; border-color: #d93025; }

.duration { color: #888; font-size: 13px; margin-bottom: 20px; }

.segment {
  padding: 12px 16px;
  background: white;
  border-radius: 8px;
  margin-bottom: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.seg-meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}
.seg-speaker {
  font-size: 12px;
  font-weight: 600;
  color: #1a73e8;
  background: #e8f0fe;
  padding: 2px 8px;
  border-radius: 4px;
}
.seg-speaker.noSpeaker { color: #999; background: #f0f0f0; }
.seg-time { font-size: 12px; color: #aaa; font-variant-numeric: tabular-nums; }
.seg-text { font-size: 15px; line-height: 1.6; }

.full-text pre {
  white-space: pre-wrap;
  font-family: inherit;
  font-size: 15px;
  line-height: 1.8;
  background: white;
  padding: 20px;
  border-radius: 8px;
}

.empty-hint { color: #888; text-align: center; padding: 32px; }
.empty-detail { color: #d93025; margin-top: 12px; font-size: 13px; white-space: pre-wrap; }

.footer-actions {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #eee;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}
.export-group { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.footer-label { font-size: 12px; color: #888; margin-right: 4px; }
.footer-right { display: flex; align-items: center; gap: 8px; }

.status-box { padding: 12px; background: #e8f0fe; border-radius: 8px; color: #1a73e8; }
.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; margin-bottom: 12px; }
.error-state { text-align: center; padding: 48px 16px; }
.error-actions { display: flex; gap: 8px; justify-content: center; margin-top: 16px; }

@media (max-width: 640px) {
  .page { max-width: 100%; }
  .header { flex-direction: column; align-items: stretch; }
  h1 { font-size: 20px; }
  .header-actions { justify-content: flex-end; }
  .audio-controls { flex-wrap: wrap; }
  .seek-slider { width: 80px; }
  .footer-actions { flex-direction: column; align-items: stretch; }
  .export-group { justify-content: flex-start; }
}
</style>
