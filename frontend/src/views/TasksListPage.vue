<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard,
  NButton,
  NSpace,
  NTag,
  NSpin,
  NEmpty,
  NAlert,
  NText,
  useDialog,
  useMessage,
} from 'naive-ui'
import { api, TaskListItem } from '../api/client'
import { formatDuration } from '../utils/format'

const router = useRouter()
const dialog = useDialog()
const message = useMessage()
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

function statusType(s: string): 'success' | 'info' | 'warning' | 'error' | 'default' {
  return ({
    done: 'success',
    processing: 'info',
    pending: 'warning',
    error: 'error',
  } as const)[s as 'done' | 'processing' | 'pending' | 'error'] || 'default'
}

function statusLabel(s: string): string {
  return ({ pending: '等待中', processing: '转写中', done: '已完成', error: '失败' } as Record<string, string>)[s] || s
}

function taskIcon(hasMinutes: boolean, hasTranscript: boolean): string {
  return hasMinutes ? '📋' : hasTranscript ? '📝' : '🎙️'
}

function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  } catch {
    return iso
  }
}

function openTask(t: TaskListItem) {
  router.push(`/transcript/${t.id}`)
}

function goToMinutes(t: TaskListItem) {
  router.push(`/minutes/${t.id}`)
}

function removeTask(t: TaskListItem) {
  dialog.warning({
    title: '确认删除',
    content: `确认删除「${t.filename}」？此操作不可撤销。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.deleteTask(t.id)
        tasks.value = tasks.value.filter(x => x.id !== t.id)
        message.success('已删除')
      } catch (e: any) {
        message.error(e.message || '删除失败')
      }
    },
  })
}
</script>

<template>
  <div>
    <NSpace align="center" justify="space-between" style="margin-bottom: 16px;">
      <h1 style="font-size: 24px; margin: 0;">历史任务</h1>
      <NButton @click="load" :loading="loading" ghost>刷新</NButton>
    </NSpace>

    <NAlert v-if="error" type="error" :title="error" style="margin-bottom: 16px;" />

    <NSpin :show="loading">
      <NEmpty
        v-if="!loading && !tasks.length"
        description="暂无任务"
        style="padding: 60px 20px;"
      >
        <template #extra>
          <NSpace>
            <RouterLink to="/upload" style="text-decoration: none;">
              <NButton type="primary" ghost>上传文件</NButton>
            </RouterLink>
            <RouterLink to="/record" style="text-decoration: none;">
              <NButton type="primary" ghost>录制</NButton>
            </RouterLink>
          </NSpace>
        </template>
      </NEmpty>

      <NSpace v-else vertical :size="8">
        <NCard
          v-for="t in tasks"
          :key="t.id"
          hoverable
          size="small"
          style="cursor: pointer;"
          @click="openTask(t)"
        >
          <div style="display: flex; align-items: center; width: 100%; gap: 14px;">
            <div style="font-size: 22px; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; background: #f0f6ff; border-radius: 8px; flex-shrink: 0;">
              {{ taskIcon(t.has_minutes, t.has_transcript) }}
            </div>
            <div style="flex: 1; min-width: 0;">
              <NText style="font-size: 14px; font-weight: 500; display: block; margin-bottom: 4px;">
                {{ t.filename }}
              </NText>
              <NSpace align="center" :size="8" :wrap-item="false">
                <NTag :type="statusType(t.status)" size="small" round>
                  {{ statusLabel(t.status) }}
                </NTag>
                <NText depth="3" style="font-size: 12px;">
                  {{ formatDateTime(t.created_at) }}
                </NText>
                <NText v-if="t.duration" depth="3" style="font-size: 12px;">
                  · {{ formatDuration(t.duration) }}
                </NText>
              </NSpace>
              <NText v-if="t.error" type="error" style="font-size: 12px; display: block; margin-top: 6px;">
                {{ t.error }}
              </NText>
            </div>
            <NSpace :size="8" @click.stop>
              <NButton
                v-if="t.has_minutes"
                size="small"
                @click.stop="goToMinutes(t)"
              >
                查看纪要
              </NButton>
              <NButton
                size="small"
                quaternary
                type="error"
                @click.stop="removeTask(t)"
                title="删除"
              >×</NButton>
            </NSpace>
          </div>
        </NCard>
      </NSpace>
    </NSpin>
  </div>
</template>
