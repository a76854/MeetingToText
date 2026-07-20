<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'

const router = useRouter()
const uploading = ref(false)
const error = ref('')
const dragOver = ref(false)

function onDragOver(e: DragEvent) {
  e.preventDefault()
  dragOver.value = true
}
function onDragLeave() { dragOver.value = false }
function onDrop(e: DragEvent) {
  e.preventDefault()
  dragOver.value = false
  const files = e.dataTransfer?.files
  if (files?.length) uploadFile(files[0])
}

async function uploadFile(file: File) {
  error.value = ''
  uploading.value = true
  try {
    const res = await api.upload(file)
    let task_id = res.task_id
    try {
      await api.startTranscribe(task_id)
    } catch {
      // transcribe 失败也能看到任务详情页，可手动重试
    }
    router.push(`/transcript/${task_id}`)
  } catch (e: any) {
    error.value = e.message || '上传失败'
  } finally {
    uploading.value = false
  }
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.length) uploadFile(input.files[0])
}
</script>

<template>
  <div class="page">
    <h1>上传音频文件</h1>
    <p class="subtitle">支持 WAV, MP3, M4A, FLAC, OGG, WebM 等格式</p>

    <div class="upload-area" :class="{ dragover: dragOver }" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop">
      <input type="file" id="fileInput" accept=".wav,.mp3,.m4a,.flac,.ogg,.webm,.opus,.aac,.wma" @change="onFileChange" :disabled="uploading" />
      <label for="fileInput" class="upload-label">
        <div class="upload-icon">+</div>
        <div>点击选择文件或拖拽文件到此处</div>
        <div class="upload-hint">限 500MB 以内</div>
      </label>
    </div>

    <div v-if="uploading" class="status-box">上传中...</div>
    <div v-if="error" class="error-box">{{ error }}</div>
  </div>
</template>

<style scoped>
.page { max-width: 600px; margin: 0 auto; }
h1 { font-size: 24px; margin-bottom: 8px; }
.subtitle { color: #888; font-size: 14px; margin-bottom: 24px; }

.upload-area {
  border: 2px dashed #ccc;
  border-radius: 12px;
  padding: 48px;
  text-align: center;
  transition: border-color 0.2s;
}
.upload-area.dragover { border-color: #1a73e8; background: #f0f6ff; }
.upload-area input[type="file"] { display: none; }
.upload-label { cursor: pointer; color: #666; }
.upload-icon { font-size: 48px; color: #1a73e8; margin-bottom: 12px; }
.upload-hint { font-size: 12px; color: #aaa; margin-top: 8px; }

.status-box { padding: 12px; background: #e8f0fe; border-radius: 8px; color: #1a73e8; margin-top: 16px; }
.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; margin-top: 16px; }

@media (max-width: 640px) {
  .page { max-width: 100%; }
  h1 { font-size: 20px; }
  .upload-area { padding: 32px 16px; }
  .upload-icon { font-size: 36px; }
}
</style>
