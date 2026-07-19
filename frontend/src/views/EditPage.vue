<script setup lang="ts">
import { ref, onMounted, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'

const route = useRoute()
const router = useRouter()
const taskId = route.params.taskId as string

const loading = ref(true)
const saving = ref(false)
const saveMessage = ref('')
const segments = ref<any[]>([])
const error = ref('')

onMounted(async () => {
  try {
    const data = await api.getTranscript(taskId)
    segments.value = (data.segments || []).map((s: any) => ({ ...s }))
    nextTick(autoSizeAll)
  } catch (e: any) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
})

function formatTime(s: number) {
  if (!s && s !== 0) return ''
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}

function autoSizeAll() {
  document.querySelectorAll<HTMLTextAreaElement>('.edit-segment .inp-text').forEach(el => {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 400) + 'px'
  })
}

function autoResizeTextarea(e: Event) {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 400) + 'px'
}

function addSegment() {
  const last = segments.value[segments.value.length - 1]
  const start = last ? last.end : 0
  segments.value.push({ start, end: start + 5, speaker: last?.speaker || '', text: '' })
  nextTick(() => {
    autoSizeAll()
    const list = document.querySelectorAll<HTMLTextAreaElement>('.edit-segment .inp-text')
    const last = list[list.length - 1]
    if (last) last.focus()
  })
}

function removeSegment(i: number) {
  segments.value.splice(i, 1)
}

function moveSegment(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= segments.value.length) return
  const tmp = segments.value[i]
  segments.value[i] = segments.value[j]
  segments.value[j] = tmp
}

async function saveEdits() {
  saving.value = true
  saveMessage.value = ''
  try {
    const cleaned = segments.value
      .filter(s => s.text && s.text.trim())
      .map(s => ({
        start: Number(s.start) || 0,
        end: Number(s.end) || 0,
        speaker: s.speaker || '',
        text: s.text,
      }))
    await api.updateTranscript(taskId, cleaned)
    saveMessage.value = `已保存 (${cleaned.length} 段)`
    setTimeout(() => router.push(`/transcript/${taskId}`), 800)
  } catch (e: any) {
    saveMessage.value = '保存失败: ' + (e.message || e)
  } finally {
    saving.value = false
  }
}

const speakers = computed(() => {
  const set = new Set<string>()
  for (const s of segments.value) {
    if (s.speaker) set.add(s.speaker)
  }
  return Array.from(set)
})
</script>

<template>
  <div class="page">
    <div class="header">
      <h1>编辑转录</h1>
      <button class="btn-primary header-spacer" @click="addSegment">+ 新增段落</button>
      <button class="btn-primary" @click="saveEdits" :disabled="saving">{{ saving ? '保存中...' : '保存修改' }}</button>
    </div>

    <div v-if="loading" class="status-box">加载中...</div>
    <div v-if="error" class="error-box">{{ error }}</div>
    <div v-if="saveMessage" class="info-box">{{ saveMessage }}</div>

    <div v-if="!loading && !error" class="edit-mode">
      <div v-for="(seg, i) in segments" :key="i" class="edit-segment">
        <div class="edit-row">
          <input
            v-model="seg.speaker"
            :list="'speakers-' + taskId"
            placeholder="说话人"
            class="inp-speaker"
          />
          <datalist :id="'speakers-' + taskId">
            <option v-for="sp in speakers" :key="sp" :value="sp" />
          </datalist>
          <input
            v-model.number="seg.start"
            type="number" step="0.1" min="0"
            class="inp-time"
          />
          <span class="dash">–</span>
          <input
            v-model.number="seg.end"
            type="number" step="0.1" min="0"
            class="inp-time"
          />
          <span class="seg-unit">秒</span>
          <div class="seg-actions">
            <button class="btn-mini" @click="moveSegment(i, -1)" :disabled="i === 0" title="上移">↑</button>
            <button class="btn-mini" @click="moveSegment(i, 1)" :disabled="i === segments.length - 1" title="下移">↓</button>
            <button class="btn-mini danger" @click="removeSegment(i)" title="删除">×</button>
          </div>
        </div>
        <textarea
          v-model="seg.text"
          class="inp-text"
          rows="4"
          @input="autoResizeTextarea"
        />
      </div>
      <div v-if="!segments.length" class="empty-hint">
        还没有任何段落，点「+ 新增一段」开始。
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 760px; margin: 0 auto; }

.header {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
  gap: 12px;
}
h1 { font-size: 24px; margin: 0; }
.header-spacer { margin-left: auto; }

.btn-primary, .btn-secondary {
  font-family: inherit;
  cursor: pointer;
  border-radius: 8px;
  border: 1px solid transparent;
  transition: all 0.15s;
  padding: 8px 16px;
  font-size: 13px;
}
.btn-primary {
  background: #1a73e8;
  color: white;
  border-color: #1a73e8;
}
.btn-primary:hover:not(:disabled) { background: #1557b0; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary {
  background: white;
  color: #1a73e8;
  border-color: #1a73e8;
}
.btn-secondary:hover { background: #f0f6ff; }

.status-box { padding: 12px; background: #e8f0fe; border-radius: 8px; color: #1a73e8; }
.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; margin-bottom: 12px; }
.info-box { padding: 10px 14px; background: #e6f4ea; border-radius: 8px; color: #137333; margin-bottom: 12px; font-size: 13px; }

.edit-mode { display: flex; flex-direction: column; gap: 10px; }

.edit-segment {
  background: white;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 12px 14px;
}
.edit-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.inp-speaker {
  width: 100px;
  padding: 6px 8px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
}
.inp-time {
  width: 70px;
  padding: 6px 8px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  text-align: center;
}
.dash { color: #999; font-size: 13px; }
.seg-unit { font-size: 12px; color: #999; }
.seg-actions { display: flex; gap: 4px; margin-left: auto; }
.btn-mini {
  width: 32px;
  height: 32px;
  border: 1px solid #ddd;
  background: white;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #444;
}
.btn-mini:hover:not(:disabled) { border-color: #1a73e8; color: #1a73e8; }
.btn-mini.danger:hover { border-color: #d93025; color: #d93025; background: #fff5f5; }
.btn-mini:disabled { opacity: 0.3; cursor: not-allowed; }

.inp-text {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
  font-family: inherit;
  line-height: 1.6;
  resize: vertical;
  box-sizing: border-box;
  min-height: 100px;
}

.empty-hint { color: #888; text-align: center; padding: 32px; }

@media (max-width: 640px) {
  .page { max-width: 100%; }
  h1 { font-size: 20px; }
  .edit-row { gap: 4px; flex-wrap: nowrap; }
  .inp-speaker { width: 72px; min-height: 36px; padding: 6px; }
  .inp-time { width: 48px; min-height: 36px; padding: 6px; }
  .btn-mini { width: 28px; height: 28px; font-size: 13px; }
  .seg-unit { font-size: 11px; }
  .dash { font-size: 12px; }
  .inp-text { font-size: 16px; min-height: 120px; }
}
</style>
