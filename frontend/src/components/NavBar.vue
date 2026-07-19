<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'
import { state as recState, timer as recTimer, cancelRecording } from '../composables/recorder'

const route = useRoute()
const isActive = (name: string) => computed(() => route.name === name ? 'active' : '')
</script>

<template>
  <nav class="navbar">
    <div class="nav-brand">MeetingToText</div>
    <div class="nav-links">
      <RouterLink to="/upload" :class="isActive('upload').value">上传文件</RouterLink>
      <RouterLink to="/record" :class="isActive('record').value">实时录音</RouterLink>
      <RouterLink to="/tasks" :class="isActive('tasks').value">历史任务</RouterLink>
      <RouterLink to="/settings" :class="isActive('settings').value">设置</RouterLink>
    </div>
  </nav>
  <Teleport to="body">
    <div v-if="recState === 'recording' || recState === 'stopping'" class="recording-bar">
      <span class="rec-dot"></span>
      <span class="rec-text">{{ recState === 'stopping' ? '保存中...' : '录制中' }} {{ recTimer }}</span>
      <RouterLink to="/record" class="rec-return">返回录音</RouterLink>
      <button v-if="recState === 'recording'" class="rec-stop" @click="cancelRecording">取消</button>
    </div>
  </Teleport>
</template>

<style scoped>
.navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 0;
  border-bottom: 1px solid #e0e0e0;
  margin-bottom: 8px;
}

.nav-brand {
  font-size: 20px;
  font-weight: 700;
  color: #1a73e8;
}

.nav-links {
  display: flex;
  gap: 24px;
}

.nav-links a {
  text-decoration: none;
  color: #666;
  font-size: 14px;
  padding: 6px 0;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.nav-links a:hover,
.nav-links a.active {
  color: #1a73e8;
  border-bottom-color: #1a73e8;
}

@media (max-width: 640px) {
  .navbar { padding: 12px 0; flex-wrap: wrap; gap: 8px; }
  .nav-brand { font-size: 16px; }
  .nav-links { gap: 14px; flex-wrap: wrap; }
  .nav-links a { font-size: 13px; padding: 4px 0; }
}

.recording-bar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: #d93025;
  color: white;
  font-size: 13px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.2);
}
.rec-dot {
  width: 10px;
  height: 10px;
  background: white;
  border-radius: 50%;
  animation: rec-blink 1s infinite;
  flex-shrink: 0;
}
@keyframes rec-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }
.rec-text { flex: 1; font-weight: 500; }
.rec-return {
  color: white;
  text-decoration: none;
  font-size: 12px;
  padding: 4px 10px;
  background: rgba(255,255,255,0.2);
  border-radius: 4px;
}
.rec-return:hover { background: rgba(255,255,255,0.3); }
.rec-stop {
  background: transparent;
  border: 1px solid rgba(255,255,255,0.5);
  color: white;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}
.rec-stop:hover { background: rgba(255,255,255,0.15); }
</style>
