import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const currentTaskId = ref<string>('')
  const activeTab = ref<'upload' | 'record'>('upload')

  function setTaskId(id: string) {
    currentTaskId.value = id
  }

  return { currentTaskId, activeTab, setTaskId }
})
