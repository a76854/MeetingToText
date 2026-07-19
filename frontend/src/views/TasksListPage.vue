<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, TaskListItem } from '../api/client'

const router = useRouter()
const tasks = ref<TaskListItem[]>([])
const loading = ref(true)
const error = ref('')

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.listTasks()
    tasks.value = res.tasks
  } catch (e: any) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function statusLabel(s: string): string {
  return { pending: '等待中', processing: '转写中', done: '已完成', error: '失败' }[s] || s
}

function statusColor(s: string): string {
  return { done: '#137333', processing: '#1a73e8', pending: '#856404', error: '#d93025' }[s] || '#666'
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  } catch {
    return iso
  }
}

function formatDuration(s: number): string {
  if (!s) return '–'
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}

function openTask(t: TaskListItem) {
  if (t.status === 'done' || t.status === 'processing') {
    router.push(`/transcript/${t.id}`)
  } else {
    router.push(`/transcript/${t.id}`)
  }
}

async function removeTask(t: TaskListItem, e: Event) {
  e.stopPropagation()
  if (!confirm(`确认删除「${t.filename}」？此操作不可撤销。`)) return
  try {
    await api.deleteTask(t.id)
    tasks.value = tasks.value.filter(x => x.id !== t.id)
  } catch (e: any) {
    error.value = e.message || '删除失败'
  }
}
</script>

<template>
  <div class="page">
    <div class="header">
      <h1>历史任务</h1>
      <button class="btn-refresh" @click="load" :disabled="loading">{{ loading ? '加载中...' : '刷新' }}</button>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="!loading && !tasks.length" class="empty-hint">
      暂无任务。<RouterLink to="/upload">上传文件</RouterLink> 或 <RouterLink to="/record">录制</RouterLink> 第一个吧。
    </div>

    <div class="task-list">
      <div
        v-for="t in tasks" :key="t.id"
        class="task-card"
        @click="openTask(t)"
      >
        <div class="task-icon">
          {{ t.has_minutes ? '📋' : t.has_transcript ? '📝' : '🎙️' }}
        </div>
        <div class="task-main">
          <div class="task-name">{{ t.filename }}</div>
          <div class="task-meta">
            <span class="status" :style="{ color: statusColor(t.status) }">● {{ statusLabel(t.status) }}</span>
            <span class="dot">·</span>
            <span>{{ formatTime(t.created_at) }}</span>
            <span v-if="t.duration" class="dot">·</span>
            <span v-if="t.duration">{{ formatDuration(t.duration) }}</span>
          </div>
          <div v-if="t.error" class="task-error">{{ t.error }}</div>
        </div>
        <button class="btn-delete" @click="removeTask(t, $event)" title="删除">×</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 800px; margin: 0 auto; }

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
h1 { font-size: 24px; }

.btn-refresh {
  padding: 8px 16px;
  background: white;
  border: 1px solid #ddd;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: #444;
}
.btn-refresh:hover:not(:disabled) { border-color: #1a73e8; color: #1a73e8; }
.btn-refresh:disabled { opacity: 0.5; }

.empty-hint {
  text-align: center;
  padding: 60px 20px;
  color: #888;
  font-size: 14px;
}
.empty-hint a { color: #1a73e8; text-decoration: none; }
.empty-hint a:hover { text-decoration: underline; }

.task-list { display: flex; flex-direction: column; gap: 8px; }

.task-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  background: white;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  cursor: pointer;
  transition: transform 0.1s, box-shadow 0.1s;
}
.task-card:hover {
  transform: translateX(2px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.task-icon {
  font-size: 22px;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f6ff;
  border-radius: 8px;
  flex-shrink: 0;
}

.task-main { flex: 1; min-width: 0; }
.task-name {
  font-size: 14px;
  font-weight: 500;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}
.task-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #888;
  flex-wrap: wrap;
}
.task-meta .dot { color: #ccc; }
.task-meta .status { font-weight: 500; }
.task-error {
  margin-top: 6px;
  font-size: 12px;
  color: #d93025;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.btn-delete {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: #aaa;
  font-size: 18px;
  border-radius: 6px;
  cursor: pointer;
  flex-shrink: 0;
}
.btn-delete:hover { background: #fce8e6; color: #d93025; }

.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; margin-bottom: 16px; }

@media (max-width: 640px) {
  .page { max-width: 100%; }
  h1 { font-size: 20px; }
  .task-card { padding: 12px; gap: 10px; }
  .task-icon { width: 36px; height: 36px; font-size: 18px; }
  .task-name { font-size: 13px; }
  .task-meta { font-size: 11px; gap: 6px; }
  .btn-delete { width: 32px; height: 32px; font-size: 20px; }
}
</style>
