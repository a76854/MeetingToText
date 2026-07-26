<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import {
  NCard,
  NButton,
  NSpace,
  NInput,
  NSpin,
  NAlert,
  useMessage,
  useDialog,
} from 'naive-ui'
import { api } from '../api/client'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const taskId = route.params.taskId as string

const loading = ref(true)
const minutes = ref('')
const error = ref('')
const editing = ref(false)
const saving = ref(false)

marked.setOptions({ breaks: true, gfm: true })

onMounted(loadMinutes)

async function loadMinutes() {
  loading.value = true
  error.value = ''
  try {
    const task = await api.getTask(taskId)
    if (!task.minutes) {
      error.value = '尚未生成会议纪要'
    } else {
      minutes.value = task.minutes
    }
  } catch (e: any) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const minutesHtml = computed(() => minutes.value ? marked.parse(minutes.value) as string : '')

function copyToClipboard() {
  navigator.clipboard.writeText(minutes.value)
  message.success('已复制到剪贴板')
}

function downloadMd() {
  const blob = new Blob([minutes.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `纪要-${taskId}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function startEdit() {
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  loadMinutes()
}

function confirmEdit() {
  dialog.warning({
    title: '确认保存',
    content: '保存后将覆盖 AI 生成的纪要内容。',
    positiveText: '保存',
    negativeText: '取消',
    onPositiveClick: async () => {
      saving.value = true
      try {
        const res = await api.updateMinutes(taskId, minutes.value)
        minutes.value = res.minutes
        editing.value = false
        message.success('已保存')
      } catch (e: any) {
        message.error(e.message || '保存失败')
      } finally {
        saving.value = false
      }
    },
  })
}

function goToGenerate() {
  router.push(`/generate/${taskId}`)
}


</script>

<template>
  <div>
    <NSpace align="center" justify="space-between" style="margin-bottom: 16px;">
      <h1 style="font-size: 24px; margin: 0;">会议纪要</h1>
      <NSpace>
        <template v-if="!editing">
          <NButton size="small" @click="downloadMd" ghost>导出</NButton>
          <NButton size="small" @click="copyToClipboard" ghost>复制</NButton>
          <NButton size="small" type="primary" @click="startEdit">编辑</NButton>
        </template>
        <template v-else>
          <NButton size="small" @click="cancelEdit" ghost>取消</NButton>
          <NButton size="small" type="primary" :loading="saving" @click="confirmEdit">保存</NButton>
        </template>
        <NButton @click="goToGenerate" ghost>重新生成</NButton>
      </NSpace>
    </NSpace>

    <NAlert v-if="error" type="error" :title="error" style="margin-bottom: 16px;" />

    <NSpin :show="loading">
      <NCard v-if="minutes">

        <NInput
          v-if="editing"
          v-model:value="minutes"
          type="textarea"
          :autosize="{ minRows: 10, maxRows: 60 }"
          style="font-size: 14px; line-height: 1.8; font-family: monospace;"
        />
        <div v-else class="minutes-content" v-html="minutesHtml" />
      </NCard>
    </NSpin>
  </div>
</template>

<style scoped>
.minutes-content {
  font-size: 15px;
  line-height: 1.8;
}
.minutes-content :deep(h1) { font-size: 22px; margin: 18px 0 10px; border-bottom: 1px solid #eee; padding-bottom: 6px; }
.minutes-content :deep(h2) { font-size: 18px; margin: 16px 0 8px; }
.minutes-content :deep(h3) { font-size: 16px; margin: 12px 0 6px; }
.minutes-content :deep(h4) { font-size: 15px; margin: 10px 0 4px; }
.minutes-content :deep(p) { margin: 8px 0; }
.minutes-content :deep(ul),
.minutes-content :deep(ol) { padding-left: 24px; margin: 8px 0; }
.minutes-content :deep(li) { margin: 4px 0; }
.minutes-content :deep(strong) { font-weight: 600; }
.minutes-content :deep(code) { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; font-size: 13px; }
.minutes-content :deep(pre) { background: #f5f5f5; padding: 12px; border-radius: 6px; overflow-x: auto; }
.minutes-content :deep(blockquote) { border-left: 3px solid #ddd; padding-left: 12px; color: #666; margin: 8px 0; }
.minutes-content :deep(table) { border-collapse: collapse; margin: 8px 0; width: 100%; }
.minutes-content :deep(th),
.minutes-content :deep(td) { border: 1px solid #ddd; padding: 6px 10px; }
.minutes-content :deep(th) { background: #f7f7f7; }
</style>
