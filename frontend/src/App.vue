<script setup lang="ts">
import { RouterView } from 'vue-router'
import NavBar from './components/NavBar.vue'
</script>

<template>
  <div class="app-container">
    <NavBar />
    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  -webkit-text-size-adjust: 100%;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: #f5f7fa;
  color: #333;
  min-height: 100vh;
  -webkit-tap-highlight-color: transparent;
}

input, textarea, select, button {
  font-family: inherit;
}

.app-container {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 20px;
}

.main-content {
  padding: 24px 0;
}

@media (max-width: 640px) {
  .app-container { padding: 0 12px; }
  .main-content { padding: 16px 0; }
}
</style>
