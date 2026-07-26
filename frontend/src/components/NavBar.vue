<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()

const navItems = [
  { name: 'record', label: '实时录音', to: '/record' },
  { name: 'upload', label: '上传文件', to: '/upload' },
  { name: 'tasks', label: '历史任务', to: '/tasks' },
  { name: 'settings', label: '设置', to: '/settings' },
] as const

const activeName = computed(() => route.name as string)
</script>

<template>
  <header class="navbar">
    <div class="nav-brand">MeetingToText</div>
    <nav class="nav-links">
      <RouterLink
        v-for="item in navItems"
        :key="item.name"
        :to="item.to"
        class="nav-link"
        :class="{ active: activeName === item.name }"
      >
        {{ item.label }}
      </RouterLink>
    </nav>
  </header>
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

.nav-link {
  text-decoration: none;
  color: #666;
  font-size: 14px;
  padding: 6px 0;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.nav-link:hover,
.nav-link.active {
  color: #1a73e8;
  border-bottom-color: #1a73e8;
}

@media (max-width: 640px) {
  .navbar { padding: 12px 0; flex-wrap: wrap; gap: 8px; }
  .nav-brand { font-size: 16px; }
  .nav-links { gap: 14px; flex-wrap: wrap; }
  .nav-link { font-size: 13px; padding: 4px 0; }
}
</style>
