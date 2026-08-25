<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import MarkdownView from '../components/MarkdownView.vue'
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
import { copyWithFeedback } from '../utils/clipboard'
import { downloadText } from '../utils/download'

const route = useRoute()
const message = useMessage()
const dialog = useDialog()
const taskId = route.params.taskId as string

const loading = ref(true)
const minutes = ref('')
const error = ref('')
const editing = ref(false)
const saving = ref(false)

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

function copyToClipboard() {
  copyWithFeedback(minutes.value, message)
}

function downloadMd() {
  downloadText(`纪要-${taskId}.md`, minutes.value)
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


</script>

<template>
  <div>
    <NSpace
      align="center"
      justify="space-between"
      style="margin-bottom: 16px;"
    >
      <h1 style="font-size: 24px; margin: 0;">
        会议纪要
      </h1>
      <NSpace>
        <template v-if="!editing">
          <NButton
            size="small"
            ghost
            @click="downloadMd"
          >
            导出
          </NButton>
          <NButton
            size="small"
            ghost
            @click="copyToClipboard"
          >
            复制
          </NButton>
          <NButton
            size="small"
            type="primary"
            @click="startEdit"
          >
            编辑
          </NButton>
        </template>
        <template v-else>
          <NButton
            size="small"
            ghost
            @click="cancelEdit"
          >
            取消
          </NButton>
          <NButton
            size="small"
            type="primary"
            :loading="saving"
            @click="confirmEdit"
          >
            保存
          </NButton>
        </template>
      </NSpace>
    </NSpace>

    <NAlert
      v-if="error"
      type="error"
      :title="error"
      style="margin-bottom: 16px;"
    />

    <NSpin :show="loading">
      <NCard v-if="minutes">
        <NInput
          v-if="editing"
          v-model:value="minutes"
          type="textarea"
          :autosize="{ minRows: 10, maxRows: 60 }"
          style="font-size: 14px; line-height: 1.8; font-family: monospace;"
        />
        <MarkdownView
          v-else
          :source="minutes"
        />
      </NCard>
    </NSpin>
  </div>
</template>

