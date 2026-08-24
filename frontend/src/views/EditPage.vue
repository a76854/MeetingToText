<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NCard,
  NButton,
  NSpace,
  NInput,
  NInputNumber,
  NSpin,
  NEmpty,
  useMessage,
} from 'naive-ui'
import { api } from '../api/client'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const taskId = route.params.taskId as string

// Default length (seconds) for a newly added transcript segment.
const NEW_SEGMENT_DURATION_S = 5

const loading = ref(true)
const saving = ref(false)
const segments = ref<any[]>([])
const error = ref('')

onMounted(async () => {
  try {
    const data = await api.getTranscript(taskId)
    segments.value = (data.segments || []).map((s: any) => ({ ...s }))
  } catch (e: any) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
})

function addSegment() {
  const last = segments.value[segments.value.length - 1]
  const start = last ? last.end : 0
  segments.value.push({ start, end: start + NEW_SEGMENT_DURATION_S, speaker: last?.speaker || '', text: '' })
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
    message.success(`已保存 (${cleaned.length} 段)`)
    setTimeout(() => router.push(`/transcript/${taskId}`), 800)
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || e))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div>
    <NSpace align="center" justify="space-between" style="margin-bottom: 16px;">
      <h1 style="font-size: 24px; margin: 0;">编辑转录</h1>
      <NSpace>
        <NButton @click="addSegment" type="primary" ghost>+ 新增段落</NButton>
        <NButton @click="saveEdits" type="primary" :loading="saving">保存修改</NButton>
      </NSpace>
    </NSpace>

    <NAlert v-if="error" type="error" :title="error" style="margin-bottom: 16px;" />

    <NSpin :show="loading">
      <NSpace v-if="!loading && !error" vertical :size="12">
        <NCard v-for="(seg, i) in segments" :key="i" size="small">
          <NSpace align="center" :size="8" wrap style="margin-bottom: 10px;">
            <NInput
              v-model:value="seg.speaker"
              :placeholder="'说话人'"
              style="width: 120px;"
              clearable
            />
            <NInputNumber
              v-model:value="seg.start"
              :step="0.1"
              :min="0"
              :show-button="false"
              style="width: 80px;"
              placeholder="开始"
            />
            <span style="color: #999;">–</span>
            <NInputNumber
              v-model:value="seg.end"
              :step="0.1"
              :min="0"
              :show-button="false"
              style="width: 80px;"
              placeholder="结束"
            />
            <span style="font-size: 12px; color: #999;">秒</span>
            <NSpace style="margin-left: auto;">
              <NButton
                size="small"
                quaternary
                :disabled="i === 0"
                @click="moveSegment(i, -1)"
                title="上移"
              >↑</NButton>
              <NButton
                size="small"
                quaternary
                :disabled="i === segments.length - 1"
                @click="moveSegment(i, 1)"
                title="下移"
              >↓</NButton>
              <NButton
                size="small"
                quaternary
                type="error"
                @click="removeSegment(i)"
                title="删除"
              >×</NButton>
            </NSpace>
          </NSpace>
          <NInput
            v-model:value="seg.text"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 12 }"
            placeholder="转录文本..."
            style="font-size: 14px; line-height: 1.6;"
          />
        </NCard>
        <NEmpty
          v-if="!segments.length"
          description="还没有任何段落，点「+ 新增段落」开始。"
        />
      </NSpace>
    </NSpin>
  </div>
</template>
