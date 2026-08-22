<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard,
  NButton,
  NSpace,
  NSwitch,
  NSpin,
  NAlert,
} from 'naive-ui'
import {
  state, error, warning, timer, volume,
  streamingAsrEnabled, liveText, liveStatus, liveError,
  startRecording, stopRecording, cancelRecording,
  loadSettings, toggleStreamingAsr,
} from '../composables/recorder'

const router = useRouter()

onMounted(async () => {
  await loadSettings()
})
</script>

<template>
  <div>
    <h1 style="font-size: 24px; margin-bottom: 8px; text-align: center;">实时录音</h1>
    <p style="color: #888; font-size: 14px; margin-bottom: 24px; text-align: center;">
      使用浏览器麦克风录制会议音频
    </p>

    <NCard>
      <NSpace vertical :size="20" align="center" style="padding: 16px 0;">
        <div v-if="state === 'idle'" style="text-align: center; color: #666; font-size: 15px;">
          <div style="font-size: 40px; margin-bottom: 12px;">🎤</div>
          <div>点击下方按钮开始录音</div>
          <div style="font-size: 12px; color: #aaa; margin-top: 8px;">录制完成后将自动生成转录</div>
          <div style="margin-top: 16px;">
            <NSpace align="center">
              <NSwitch :value="streamingAsrEnabled" @update:value="toggleStreamingAsr" />
              <span style="font-size: 13px; color: #444;">实时转录</span>
            </NSpace>
          </div>
        </div>

        <NSpin v-if="state === 'preparing'" :show="true" size="large" description="正在准备...">
          <div style="min-height: 80px; min-width: 200px;"></div>
        </NSpin>

        <div v-if="state === 'cancelling'" style="text-align: center;">
          <NSpin :show="true" />
          <div style="margin-top: 12px; color: #888;">已放弃本次录音</div>
        </div>

        <div v-if="state === 'done'" style="text-align: center; color: #137333;">
          <div style="width: 40px; height: 40px; border-radius: 50%; background: #137333; color: white; display: flex; align-items: center; justify-content: center; font-size: 20px; margin: 0 auto 8px;">✓</div>
          <div>录制完成，正在跳转...</div>
        </div>

        <div v-if="state === 'recording' || state === 'stopping'" class="recording-panel">
          <div class="timer-main">{{ timer }}</div>

          <div class="volume-bars">
            <div
              v-for="i in 32" :key="i"
              class="vol-bar"
              :class="{ active: volume > (i - 1) / 32 }"
              :style="{ height: Math.max(4, 8 + Math.sin(i * 0.5) * 12 + volume * 18) + 'px' }"
            ></div>
          </div>

          <div class="recording-indicator">
            <span class="rec-dot" :class="{ stopping: state === 'stopping' }"></span>
            {{ state === 'stopping' ? '正在保存...' : '录制中' }}
          </div>
        </div>

        <div v-if="(state === 'recording' || state === 'stopping') && streamingAsrEnabled" class="live-panel">
          <div class="live-header">
            <span class="live-dot" :class="liveStatus"></span>
            <span class="live-title">实时转录</span>
            <span v-if="liveStatus === 'waiting'" class="live-warn">加载模型中...</span>
          </div>
          <div class="live-content">
            <p v-if="liveText" class="live-text">{{ liveText }}<span class="cursor">▍</span></p>
            <p v-else-if="liveStatus === 'waiting'" class="live-empty">正在启动实时转录，请稍候...</p>
            <p v-else class="live-empty">聆听中...</p>
            <p v-if="liveError" class="live-empty error">{{ liveError }}</p>
          </div>
        </div>

        <NSpace v-if="state === 'idle'" justify="center" style="width: 100%;">
          <NButton
            type="primary"
            size="large"
            round
            @click="startRecording(router)"
            style="min-width: 200px; min-height: 54px; font-size: 15px;"
          >
            <template #icon>
              <span style="font-size: 14px;">●</span>
            </template>
            开始录音
          </NButton>
        </NSpace>

        <NSpace v-else-if="state !== 'done' && state !== 'cancelling'" justify="center" style="width: 100%;">
          <NButton
            v-if="state === 'recording'"
            type="error"
            size="large"
            round
            @click="stopRecording(router)"
            style="min-width: 200px; min-height: 54px; font-size: 15px;"
          >
            <template #icon>
              <span style="font-size: 14px;">■</span>
            </template>
            停止录音
          </NButton>
          <NButton
            v-else
            size="large"
            round
            disabled
            style="min-width: 200px; min-height: 54px; font-size: 15px;"
          >
            {{ state === 'preparing' ? '准备中...' : '保存中...' }}
          </NButton>
          <NButton
            size="large"
            round
            :disabled="state === 'stopping'"
            @click="cancelRecording"
            style="min-width: 100px; min-height: 54px;"
          >
            取消
          </NButton>
        </NSpace>

        <NAlert
          v-if="error"
          type="error"
          :show-icon="false"
          @click="error = ''"
          style="cursor: pointer; max-width: 100%;"
        >
          {{ error }}
        </NAlert>

        <NAlert
          v-if="warning && state === 'recording'"
          type="warning"
          @click="warning = ''"
          style="cursor: pointer; max-width: 100%;"
        >
          ⚠ {{ warning }}
        </NAlert>

        <p v-if="state === 'idle'" style="font-size: 12px; color: #999; text-align: center; max-width: 360px;">
          录音中可随时点「取消」放弃本次录制，不会保存到历史任务。
        </p>
      </NSpace>
    </NCard>
  </div>
</template>

<style scoped>
.recording-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  width: 100%;
}

.timer-main {
  font-size: 56px;
  font-weight: 700;
  color: #d93025;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  letter-spacing: 3px;
}

.volume-bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 44px;
  width: 100%;
  max-width: 360px;
  justify-content: center;
  padding: 0 16px;
}

.vol-bar {
  flex: 1;
  max-width: 6px;
  min-height: 4px;
  border-radius: 2px;
  background: #d93025;
  opacity: 0.2;
  transition: height 0.08s ease, opacity 0.08s ease;
}
.vol-bar.active { opacity: 1; }

.recording-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #d93025;
  font-weight: 500;
}
.rec-dot {
  width: 10px;
  height: 10px;
  background: #d93025;
  border-radius: 50%;
  animation: blink 1s infinite;
}
.rec-dot.stopping { animation: none; opacity: 0.5; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }

.live-panel {
  width: 100%;
  max-width: 420px;
  background: #fafbfc;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  padding: 12px 14px;
  text-align: left;
}
.live-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #666;
  margin-bottom: 8px;
  font-weight: 500;
}
.live-title { color: #444; }
.live-warn { color: #1a73e8; font-size: 11px; margin-left: auto; }
.live-dot {
  width: 8px;
  height: 8px;
  background: #d93025;
  border-radius: 50%;
  animation: pulse 1.5s infinite;
  flex-shrink: 0;
}
.live-dot.waiting { background: #f9ab00; animation: none; }
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.3; transform: scale(0.85); }
}
.live-content {
  max-height: 180px;
  overflow-y: auto;
  font-size: 14px;
  line-height: 1.6;
  color: #222;
  -webkit-overflow-scrolling: touch;
}
.live-text { margin: 0; word-break: break-word; }
.live-empty { color: #999; font-style: italic; margin: 0; }
.live-empty.error { color: #d93025; font-style: normal; }
.cursor {
  display: inline-block;
  color: #1a73e8;
  margin-left: 1px;
  animation: cursor-blink 0.9s steps(2) infinite;
}
@keyframes cursor-blink {
  0% { opacity: 1; }
  50% { opacity: 0; }
  100% { opacity: 1; }
}

@media (max-width: 640px) {
  .timer-main { font-size: 44px; letter-spacing: 2px; }
  .volume-bars { height: 36px; }
  .vol-bar:nth-child(n+25) { display: none; }
  .live-panel { max-width: 100%; padding: 10px 12px; }
  .live-content { max-height: 140px; font-size: 13px; }
}
</style>
