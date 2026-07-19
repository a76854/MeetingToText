<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
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
const editing = ref(false)
const dirty = ref(false)
const saving = ref(false)
const saveMessage = ref('')

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
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}

function goToGenerate() {
  router.push(`/generate/${taskId}`)
}

function toggleEdit() {
  if (!editing.value) {
    segments.value = segments.value.map(s => ({ ...s }))
  }
  editing.value = !editing.value
  dirty.value = false
  saveMessage.value = ''
}

function markDirty() {
  dirty.value = true
  saveMessage.value = ''
}

function addSegment() {
  const last = segments.value[segments.value.length - 1]
  const start = last ? last.end : 0
  segments.value.push({ start, end: start + 5, speaker: last?.speaker || '', text: '' })
  markDirty()
}

function removeSegment(i: number) {
  segments.value.splice(i, 1)
  markDirty()
}

function moveSegment(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= segments.value.length) return
  const tmp = segments.value[i]
  segments.value[i] = segments.value[j]
  segments.value[j] = tmp
  markDirty()
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
    const res = await api.updateTranscript(taskId, cleaned)
    segments.value = cleaned
    fullText.value = cleaned
      .map(s => (s.speaker ? `[${s.speaker}] ${s.text}` : s.text))
      .join('\n\n')
    dirty.value = false
    saveMessage.value = `已保存 (${res.segment_count} 段)`
    setTimeout(() => { saveMessage.value = '' }, 3000)
  } catch (e: any) {
    saveMessage.value = '保存失败: ' + (e.message || e)
  } finally {
    saving.value = false
  }
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

const speakers = computed(() => {
  const set = new Set<string>()
  for (const s of segments.value) {
    if (s.speaker) set.add(s.speaker)
  }
  return Array.from(set)
})

function exportAs(format: string) {
  const url = api.exportUrl(taskId, format)
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}
</script>

<template>
  <div class="page">
    <div class="header">
      <h1>转录结果</h1>
      <div class="header-actions">
        <span v-if="status === 'processing'" class="status-badge processing">转写中...</span>
        <button v-if="status === 'done' && segments.length && !editing" class="btn-secondary" @click="goToGenerate">生成纪要 →</button>
        <button v-if="status === 'done' && !editing" class="btn-secondary" @click="toggleEdit">编辑</button>
        <button v-if="editing" class="btn-primary" @click="saveEdits" :disabled="saving || !dirty">{{ saving ? '保存中...' : '保存修改' }}</button>
        <button v-if="editing" class="btn-secondary" @click="toggleEdit">取消</button>
      </div>
    </div>

    <div v-if="loading" class="status-box">加载中...</div>
    <div v-if="error" class="error-box">{{ error }}</div>
    <div v-if="saveMessage" class="info-box">{{ saveMessage }}</div>

    <div v-if="status === 'processing' || status === 'pending'" class="processing-area">
      <ProgressIndicator v-if="progress" :progress="progress" :task="{ status }" />
      <div v-else class="status-box">正在处理转写，请稍候...</div>
    </div>

    <div v-if="status === 'done' && !error" class="transcript-container">
      <div class="duration" v-if="duration">总时长: {{ formatTime(duration) }}</div>

      <div v-if="!editing">
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

      <div v-else class="edit-mode">
        <div class="edit-toolbar">
          <span class="edit-hint">逐段编辑后点「保存修改」即可更新转录文本（生成纪要时会用最新内容）</span>
          <button class="btn-add" @click="addSegment">+ 新增一段</button>
        </div>
        <div v-for="(seg, i) in segments" :key="i" class="edit-segment">
          <div class="edit-row">
            <input
              v-model="seg.speaker"
              :list="'speakers-' + taskId"
              placeholder="说话人"
              class="inp-speaker"
              @input="markDirty"
            />
            <datalist :id="'speakers-' + taskId">
              <option v-for="sp in speakers" :key="sp" :value="sp" />
            </datalist>
            <input
              v-model.number="seg.start"
              type="number" step="0.1" min="0"
              class="inp-time"
              @input="markDirty"
            />
            <span class="dash">–</span>
            <input
              v-model.number="seg.end"
              type="number" step="0.1" min="0"
              class="inp-time"
              @input="markDirty"
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
            rows="2"
            @input="markDirty"
          />
        </div>
        <div v-if="!segments.length" class="empty-hint">
          还没有任何段落，点「+ 新增一段」开始。
        </div>
      </div>

      <div v-if="status === 'done' && (segments.length || fullText)" class="footer-actions">
        <div class="export-group">
          <span class="footer-label">导出：</span>
          <button class="btn-export" @click="exportAs('txt')">TXT</button>
          <button class="btn-export" @click="exportAs('srt')">SRT 字幕</button>
          <button class="btn-export" @click="exportAs('vtt')">VTT 字幕</button>
          <button class="btn-export" @click="exportAs('md')">Markdown</button>
          <button class="btn-export" @click="exportAs('all')">全部 (zip)</button>
        </div>
        <button class="btn-delete" @click="deleteTask">删除任务</button>
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

.edit-mode { display: flex; flex-direction: column; gap: 10px; }
.edit-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f0f6ff;
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 4px;
}
.edit-hint { font-size: 12px; color: #444; }
.btn-add {
  padding: 6px 12px;
  background: #1a73e8;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}
.btn-add:hover { background: #1557b0; }

.edit-segment {
  padding: 12px 14px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.edit-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.inp-speaker {
  width: 90px;
  padding: 4px 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 12px;
}
.inp-time {
  width: 64px;
  padding: 4px 6px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.seg-unit { font-size: 11px; color: #999; margin-right: auto; }
.dash { color: #999; }
.seg-actions { display: flex; gap: 4px; }
.btn-mini {
  width: 26px;
  height: 26px;
  border: 1px solid #ddd;
  background: white;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  color: #666;
}
.btn-mini:hover:not(:disabled) { background: #f0f0f0; }
.btn-mini:disabled { opacity: 0.3; cursor: not-allowed; }
.btn-mini.danger { color: #d93025; border-color: #f4c2c0; }
.btn-mini.danger:hover { background: #fce8e6; }

.inp-text {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
  line-height: 1.5;
}
.inp-text:focus { outline: none; border-color: #1a73e8; }
.inp-speaker:focus, .inp-time:focus { outline: none; border-color: #1a73e8; }

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

.status-box { padding: 12px; background: #e8f0fe; border-radius: 8px; color: #1a73e8; }
.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; margin-bottom: 12px; }
.info-box { padding: 10px 14px; background: #e6f4ea; border-radius: 8px; color: #137333; margin-bottom: 12px; font-size: 13px; }
</style>
