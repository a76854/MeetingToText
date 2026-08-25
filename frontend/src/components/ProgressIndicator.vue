<script setup lang="ts">
import { computed } from 'vue'
import { NSteps, NStep, NProgress } from 'naive-ui'

const props = defineProps<{
  progress: { current_step: string; steps: { name: string; status: string; message: string }[]; overall: number } | null
}>()

const stepLabels: Record<string, string> = {
  vad: '语音活动检测',
  asr: '语音识别与说话人分离',
}

const statusMap: Record<string, 'process' | 'finish' | 'error' | 'wait'> = {
  pending: 'wait',
  running: 'process',
  done: 'finish',
  error: 'error',
}

const stepItems = computed(() => {
  if (!props.progress) return []
  return props.progress.steps.map(s => ({
    title: stepLabels[s.name] || s.name,
    description: s.status === 'running' ? s.message : undefined,
    status: statusMap[s.status] || 'wait',
  }))
})

const percent = computed(() => {
  if (!props.progress) return 0
  return Math.round(props.progress.overall * 100)
})
</script>

<template>
  <div v-if="progress">
    <NProgress
      type="line"
      :percentage="percent"
      :show-indicator="true"
      :height="10"
      style="margin-bottom: 20px;"
    />
    <NSteps
      :current="stepItems.findIndex(s => s.status === 'process') + 1"
      vertical
    >
      <NStep
        v-for="(item, i) in stepItems"
        :key="i"
        :title="item.title"
        :description="item.description"
        :status="item.status"
      />
    </NSteps>
  </div>
</template>
