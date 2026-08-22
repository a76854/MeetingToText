<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import {
  NCard,
  NButton,
  NSpace,
  NInput,
  NRadioGroup,
  NRadio,
  NAlert,
  NSpin,
  NTag,
  useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { sanitizeHtml } from '../utils/sanitize'

const route = useRoute()
const router = useRouter()
const taskId = route.params.taskId as string
const message = useMessage()

const templates = ref<any[]>([])
const selectedTemplate = ref('meeting_minutes')
const customInstructions = ref('')
const generating = ref(false)
const minutes = ref('')
const error = ref('')

marked.setOptions({ breaks: true, gfm: true })

onMounted(async () => {
  try {
    const [tplRes, taskRes] = await Promise.all([
      api.getTemplates(),
      api.getTask(taskId),
    ])
    templates.value = tplRes.templates
    if (taskRes.minutes) {
      minutes.value = taskRes.minutes
    }
  } catch (e: any) {
    error.value = e.message
  }
})

function goToMinutes() {
  router.push(`/minutes/${taskId}`)
}

async function doGenerate() {
  generating.value = true
  error.value = ''
  try {
    const res = await api.generateMinutes(taskId, selectedTemplate.value, customInstructions.value)
    minutes.value = res.minutes
  } catch (e: any) {
    error.value = e.message || '生成失败'
    message.error(error.value)
  } finally {
    generating.value = false
  }
}

const minutesHtml = computed(() => minutes.value ? sanitizeHtml(minutes.value) : '')

function copyToClipboard() {
  navigator.clipboard.writeText(minutes.value)
  message.success('已复制到剪贴板')
}

function downloadMarkdown() {
  const url = api.exportUrl(taskId, 'md')
  fetch(url).then(r => r.blob()).then(blob => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = ''
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(a.href)
  })
}
</script>

<template>
  <div>
    <NSpace align="center" justify="space-between" style="margin-bottom: 24px;">
      <h1 style="font-size: 24px; margin: 0;">生成会议纪要</h1>
      <NSpace v-if="minutes">
        <NButton size="small" @click="goToMinutes" type="primary">查看纪要</NButton>
        <NButton size="small" :loading="generating" @click="doGenerate" ghost>重新生成</NButton>
      </NSpace>
    </NSpace>

    <NCard title="选择模板" style="margin-bottom: 16px;">
      <NRadioGroup v-model:value="selectedTemplate">
        <NSpace vertical :size="10" style="width: 100%;">
          <NRadio
            v-for="t in templates"
            :key="t.id"
            :value="t.id"
            style="width: 100%; align-items: flex-start;"
          >
            <div>
              <div style="font-weight: 600; font-size: 14px;">{{ t.name }}</div>
              <div style="font-size: 12px; color: #888;">{{ t.description }}</div>
            </div>
          </NRadio>
        </NSpace>
      </NRadioGroup>
    </NCard>

    <NCard title="额外要求（选填）" style="margin-bottom: 16px;">
      <NInput
        v-model:value="customInstructions"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 5 }"
        placeholder="例如：使用英文输出、重点提取技术讨论内容..."
      />
    </NCard>

    <NButton
      v-if="!minutes"
      type="primary"
      size="large"
      block
      :loading="generating"
      @click="doGenerate"
      style="margin-bottom: 16px;"
    >
      {{ generating ? '生成中...' : '生成会议纪要' }}
    </NButton>

    <NAlert v-if="error" type="error" :title="error" style="margin-bottom: 16px;" />

    <NCard v-if="minutes" title="生成结果">
      <template #header-extra>
        <NSpace>
          <NButton size="small" @click="downloadMarkdown" ghost>下载 .md</NButton>
          <NButton size="small" @click="copyToClipboard" ghost>复制</NButton>
        </NSpace>
      </template>
      <div class="minutes-content" v-html="minutesHtml" />
    </NCard>
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
