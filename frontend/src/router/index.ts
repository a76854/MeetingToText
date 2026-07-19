import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/record' },
    {
      path: '/upload',
      name: 'upload',
      component: () => import('../views/UploadPage.vue'),
    },
    {
      path: '/record',
      name: 'record',
      component: () => import('../views/RecordPage.vue'),
    },
    {
      path: '/tasks',
      name: 'tasks',
      component: () => import('../views/TasksListPage.vue'),
    },
    {
      path: '/transcript/:taskId',
      name: 'transcript',
      component: () => import('../views/TranscriptPage.vue'),
    },
    {
      path: '/generate/:taskId',
      name: 'generate',
      component: () => import('../views/GeneratePage.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsPage.vue'),
    },
    {
      path: '/edit/:taskId',
      name: 'edit',
      component: () => import('../views/EditPage.vue'),
    },
  ],
})

export default router
