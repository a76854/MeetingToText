<script setup lang="ts">
import { RouterView } from 'vue-router'
import {
  NConfigProvider,
  NMessageProvider,
  NDialogProvider,
  NNotificationProvider,
  NLoadingBarProvider,
  zhCN,
  dateZhCN,
  type GlobalThemeOverrides,
} from 'naive-ui'
import NavBar from './components/NavBar.vue'

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#1a73e8',
    primaryColorHover: '#4285f4',
    primaryColorPressed: '#1557b0',
    primaryColorSuppl: '#4285f4',
    infoColor: '#1a73e8',
    successColor: '#137333',
    warningColor: '#f9ab00',
    errorColor: '#d93025',
    bodyColor: '#f5f7fa',
    textColorBase: '#333',
    borderRadius: '8px',
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
  },
  Button: {
    borderRadiusMedium: '8px',
  },
  Card: {
    borderRadius: '12px',
  },
  Tabs: {
    tabFontWeightActive: '500',
  },
}
</script>

<template>
  <NConfigProvider
    :theme-overrides="themeOverrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
    <NLoadingBarProvider>
      <NMessageProvider>
        <NNotificationProvider>
          <NDialogProvider>
            <div class="app-container">
              <NavBar />
              <main class="main-content">
                <RouterView />
              </main>
            </div>
          </NDialogProvider>
        </NNotificationProvider>
      </NMessageProvider>
    </NLoadingBarProvider>
  </NConfigProvider>
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
