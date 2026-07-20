<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  state, taskId, error, warning, timer, volume, elapsedSec,
  streamingAsrEnabled, liveText, liveStatus, liveError,
  formatTime, startRecording, stopRecording, cancelRecording,
  loadSettings, toggleStreamingAsr,
} from '../composables/recorder'

const router = useRouter()

onMounted(async () => {
  await loadSettings()
})
</script>

<template>
  <div class="page">
    <h1>实时录音</h1>
    <p class="subtitle">使用浏览器麦克风录制会议音频</p>

    <div class="record-area">
      <div v-if="state === 'idle'" class="idle-hint">
        <div class="mic-icon">🎤</div>
        <div>点击下方按钮开始录音</div>
        <div class="idle-sub">录制完成后将自动生成转录和会议纪要</div>
        <label class="streaming-toggle">
          <input type="checkbox" :checked="streamingAsrEnabled" @change="toggleStreamingAsr(($event.target as HTMLInputElement).checked)" />
          <span>实时转录</span>
        </label>
      </div>

      <div v-if="state === 'preparing'" class="connecting-hint">
        <span class="spinner"></span>
        <span>正在准备...</span>
        <span class="hint-sub">打开麦克风并连接服务器</span>
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

      <div v-if="state === 'cancelling'" class="connecting-hint">
        <span class="spinner"></span>
        <span>已放弃本次录音</span>
      </div>

      <div v-if="state === 'done'" class="done-hint">
        <div class="done-icon">✓</div>
        <div>录制完成，正在跳转...</div>
      </div>

      <div class="button-row" :class="{ wrap: state !== 'idle' }">
        <button
          v-if="state === 'idle'"
          class="btn-record idle"
          @click="startRecording(router)"
        >
          <span class="btn-icon">●</span>
          <span>开始录音</span>
        </button>

        <template v-else-if="state !== 'done' && state !== 'cancelling'">
          <button
            v-if="state === 'preparing'"
            class="btn-record preparing"
            disabled
          >
            <span class="spinner small"></span>
            <span>准备中...</span>
          </button>

          <button
            v-else-if="state === 'recording'"
            class="btn-record recording"
            @click="stopRecording(router)"
          >
            <span class="btn-icon">■</span>
            <span>停止录音</span>
          </button>

          <button
            v-else-if="state === 'stopping'"
            class="btn-record stopping"
            disabled
          >
            <span class="spinner small"></span>
            <span>保存中...</span>
          </button>

          <button
            class="btn-cancel"
            :disabled="state === 'stopping'"
            @click="cancelRecording"
          >
            取消
          </button>
        </template>
      </div>

      <div v-if="error" class="error-box" @click="error = ''">{{ error }}</div>
      <div v-if="warning && state === 'recording'" class="warning-box" @click="warning = ''">
        <span class="warning-icon">⚠</span>
        <span>{{ warning }}</span>
      </div>

      <p v-if="state === 'idle'" class="cancel-tip">
        录音中可随时点「取消」放弃本次录制，不会保存到历史任务。
      </p>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 600px; margin: 0 auto; text-align: center; }
h1 { font-size: 24px; margin-bottom: 8px; }
.subtitle { color: #888; font-size: 14px; margin-bottom: 24px; }

.record-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  padding: 40px 32px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  min-height: 320px;
  justify-content: center;
}

.idle-hint { color: #666; font-size: 15px; }
.mic-icon { font-size: 40px; margin-bottom: 12px; }
.idle-sub { font-size: 12px; color: #aaa; margin-top: 8px; }

.streaming-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 16px;
  font-size: 13px;
  color: #444;
  cursor: pointer;
}
.streaming-toggle input { cursor: pointer; }

.connecting-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: #1a73e8;
  font-size: 14px;
}
.hint-sub { font-size: 12px; color: #999; }
.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #e0e0e0;
  border-top-color: #1a73e8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.spinner.small {
  width: 14px;
  height: 14px;
  border-width: 2px;
  display: inline-block;
  vertical-align: middle;
  margin-right: 6px;
}
@keyframes spin { to { transform: rotate(360deg); } }

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
.live-dot.active { background: #d93025; animation: pulse 1.5s infinite; }
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

.done-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #137333;
  font-size: 14px;
}
.done-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #137333;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  margin-bottom: 8px;
}

.button-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  width: 100%;
  max-width: 420px;
}
.button-row.wrap { flex-wrap: wrap; }

.btn-record, .btn-cancel {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px 28px;
  border: none;
  border-radius: 50px;
  font-size: 15px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
  -webkit-tap-highlight-color: transparent;
}
.btn-record { background: #1a73e8; color: white; min-width: 200px; min-height: 54px; }
.btn-record.idle:hover { background: #1557b0; }
.btn-record.preparing, .btn-record.stopping { background: #9aa0a6; cursor: not-allowed; }
.btn-record.recording { background: #d93025; }
.btn-record.recording:hover { background: #b71c1c; }
.btn-icon { font-size: 14px; line-height: 1; }

.btn-cancel {
  background: white;
  color: #666;
  border: 1px solid #ddd;
  min-width: 100px;
  min-height: 54px;
  padding: 15px 24px;
}
.btn-cancel:hover:not(:disabled) {
  border-color: #d93025;
  color: #d93025;
  background: #fff5f5;
}
.btn-cancel:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.cancel-tip {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
  max-width: 360px;
  line-height: 1.5;
}

.error-box {
  padding: 10px 14px;
  background: #fce8e6;
  border-radius: 8px;
  color: #d93025;
  font-size: 13px;
  cursor: pointer;
  max-width: 100%;
}

.warning-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #fff3cd;
  border-radius: 8px;
  color: #856404;
  font-size: 13px;
  cursor: pointer;
  max-width: 100%;
  text-align: left;
  line-height: 1.5;
}
.warning-box .warning-icon { flex-shrink: 0; font-size: 14px; }

@media (max-width: 640px) {
  .page { max-width: 100%; padding: 0 4px; }
  h1 { font-size: 20px; }
  .subtitle { font-size: 13px; margin-bottom: 16px; }
  .record-area { padding: 24px 16px; min-height: 280px; gap: 16px; }
  .timer-main { font-size: 44px; letter-spacing: 2px; }
  .volume-bars { height: 36px; }
  .vol-bar:nth-child(n+25) { display: none; }
  .button-row.wrap { flex-direction: column; }
  .btn-record, .btn-cancel { width: 100%; min-width: 0; }
  .live-panel { max-width: 100%; padding: 10px 12px; }
  .live-content { max-height: 140px; font-size: 13px; }
  .cancel-tip { font-size: 11px; }
}
</style>
