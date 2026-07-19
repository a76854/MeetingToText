<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'

const route = useRoute()
const router = useRouter()

const taskId = route.params.taskId as string
const loading = ref(true)
const segments = ref<any[]>([])
const fullText = ref('')
const duration = ref(0)
const error = ref('')

onMounted(async () => {
  try {
    const data = await api.getTranscript(taskId)
    segments.value = data.segments
    fullText.value = data.full_text
    duration.value = data.duration
  } catch (e: any) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
})

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
      <button class="btn-primary" @click="goToGenerate">生成会议纪要 →</button>
    </div>

    <div v-if="loading" class="status-box">加载中...</div>
    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="!loading && !error" class="transcript-container">
      <div class="duration">总时长: {{ formatTime(duration) }}</div>

      <div v-for="(seg, i) in segments" :key="i" class="segment">
        <div class="seg-meta">
          <span class="seg-speaker" :class="{ noSpeaker: !seg.speaker }">{{ seg.speaker || '未知说话人' }}</span>
          <span class="seg-time">{{ formatTime(seg.start) }} - {{ formatTime(seg.end) }}</span>
        </div>
        <div class="seg-text">{{ seg.text }}</div>
      </div>

      <div v-if="!segments.length" class="full-text">
        <pre>{{ fullText }}</pre>
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

.status-box { padding: 12px; background: #e8f0fe; border-radius: 8px; color: #1a73e8; }
.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; }
</style>
