<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()
const isActive = (name: string) => computed(() => route.name === name ? 'active' : '')
</script>

<template>
  <nav class="navbar">
    <div class="nav-brand">MeetingToText</div>
    <div class="nav-links">
      <RouterLink to="/upload" :class="isActive('upload').value">上传文件</RouterLink>
      <RouterLink to="/record" :class="isActive('record').value">实时录音</RouterLink>
      <RouterLink to="/settings" :class="isActive('settings').value">设置</RouterLink>
    </div>
  </nav>
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
</style>
