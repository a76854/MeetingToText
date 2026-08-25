<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarkdownView from '../components/MarkdownView.vue'
import {
  NCard,
  NButton,
  NSpace,
  NInput,
  NRadioGroup,
  NRadio,
  NAlert,
  useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { copyWithFeedback } from '../utils/clipboard'
import { downloadText } from '../utils/download'

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

function copyToClipboard() {
  copyWithFeedback(minutes.value, message)
}

// Downloads the minutes currently on screen. The backend /api/export endpoint
// is transcript-only (see backend/app/services/exporters.py `_export_md`), so
// exporting from here routes through the in-memory minutes instead (todo 19).
function downloadMarkdown() {
  downloadText(`纪要-${taskId}.md`, minutes.value)
}
</script>

<template>
  <div>
    <NSpace
      align="center"
      justify="space-between"
      style="margin-bottom: 24px;"
    >
      <h1 style="font-size: 24px; margin: 0;">
        生成会议纪要
      </h1>
      <NSpace v-if="minutes">
        <NButton
          size="small"
          type="primary"
          @click="goToMinutes"
        >
          查看纪要
        </NButton>
        <NButton
          size="small"
          :loading="generating"
          ghost
          @click="doGenerate"
        >
          重新生成
        </NButton>
      </NSpace>
    </NSpace>

    <NCard
      title="选择模板"
      style="margin-bottom: 16px;"
    >
      <NRadioGroup v-model:value="selectedTemplate">
        <NSpace
          vertical
          :size="10"
          style="width: 100%;"
        >
          <NRadio
            v-for="t in templates"
            :key="t.id"
            :value="t.id"
            style="width: 100%; align-items: flex-start;"
          >
            <div>
              <div style="font-weight: 600; font-size: 14px;">
                {{ t.name }}
              </div>
              <div style="font-size: 12px; color: #888;">
                {{ t.description }}
              </div>
            </div>
          </NRadio>
        </NSpace>
      </NRadioGroup>
    </NCard>

    <NCard
      title="额外要求（选填）"
      style="margin-bottom: 16px;"
    >
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
      style="margin-bottom: 16px;"
      @click="doGenerate"
    >
      {{ generating ? '生成中...' : '生成会议纪要' }}
    </NButton>

    <NAlert
      v-if="error"
      type="error"
      :title="error"
      style="margin-bottom: 16px;"
    />

    <NCard
      v-if="minutes"
      title="生成结果"
    >
      <template #header-extra>
        <NSpace>
          <NButton
            size="small"
            ghost
            @click="downloadMarkdown"
          >
            下载纪要 .md
          </NButton>
          <NButton
            size="small"
            ghost
            @click="copyToClipboard"
          >
            复制
          </NButton>
        </NSpace>
      </template>
      <MarkdownView :source="minutes" />
    </NCard>
  </div>
</template>

