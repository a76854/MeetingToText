<script setup lang="ts">
defineProps<{
  progress: { current_step: string; steps: { name: string; status: string; message: string }[]; overall: number } | null
  task: any
}>()

const stepLabels: Record<string, string> = {
  vad: '语音活动检测',
  asr: '语音识别',
  diarization: '说话人分离',
  alignment: '文本对齐',
}

const statusIcons: Record<string, string> = {
  pending: '○',
  running: '◉',
  done: '✓',
  error: '✗',
}
</script>

<template>
  <div v-if="progress" class="progress-container">
    <div class="progress-bar-bg">
      <div class="progress-bar-fill" :style="{ width: (progress.overall * 100) + '%' }" />
    </div>
    <div class="progress-steps">
      <div v-for="step in progress.steps" :key="step.name" class="step" :class="step.status">
        <span class="step-icon">{{ statusIcons[step.status] || '○' }}</span>
        <span class="step-label">{{ stepLabels[step.name] || step.name }}</span>
        <span class="step-msg" v-if="step.status === 'running'">{{ step.message }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.progress-container {
  margin-top: 24px;
  padding: 20px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}

.progress-bar-bg {
  height: 6px;
  background: #e0e0e0;
  border-radius: 3px;
  margin-bottom: 16px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: #1a73e8;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-steps { display: flex; flex-direction: column; gap: 8px; }

.step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #aaa;
}
.step.running { color: #1a73e8; font-weight: 500; }
.step.done { color: #137333; }
.step.error { color: #d93025; }

.step-icon { width: 20px; text-align: center; font-size: 12px; }
.step-label { min-width: 80px; }
.step-msg { font-size: 12px; color: #888; margin-left: auto; }
</style>
