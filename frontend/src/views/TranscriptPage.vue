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
    segments.value = data.segments
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
      segments.value = t.result?.segments || []
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
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}

function goToGenerate() {
  router.push(`/generate/${taskId}`)
}
</script>

<template>
  <div class="page">
    <div class="header">
      <h1>转录结果</h1>
      <div class="header-actions">
        <span v-if="status === 'processing'" class="status-badge processing">转写中...</span>
        <button v-if="status === 'done' && segments.length" class="btn-primary" @click="goToGenerate">生成会议纪要 →</button>
      </div>
    </div>

    <div v-if="loading" class="status-box">加载中...</div>
    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="status === 'processing' || status === 'pending'" class="processing-area">
      <ProgressIndicator v-if="progress" :progress="progress" :task="{ status }" />
      <div v-else class="status-box">正在处理转写，请稍候...</div>
    </div>

    <div v-if="status === 'done' && !error" class="transcript-container">
      <div class="duration" v-if="duration">总时长: {{ formatTime(duration) }}</div>

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
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 700px; margin: 0 auto; }

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
h1 { font-size: 24px; }

.header-actions { display: flex; align-items: center; gap: 12px; }

.status-badge {
  font-size: 13px;
  padding: 4px 12px;
  border-radius: 20px;
  font-weight: 500;
}
.status-badge.processing { background: #fff3cd; color: #856404; }

.btn-primary {
  padding: 10px 20px;
  background: #1a73e8;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-primary:hover { background: #1557b0; }

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
.seg-time { font-size: 12px; color: #aaa; }
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

.status-box { padding: 12px; background: #e8f0fe; border-radius: 8px; color: #1a73e8; }
.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; }
</style>
