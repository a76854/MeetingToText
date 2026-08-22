<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard,
  NUpload,
  NUploadDragger,
  NText,
  NSpin,
  useMessage,
  type UploadCustomRequestOptions,
  type UploadFileInfo,
} from 'naive-ui'
import { api } from '../api/client'

const router = useRouter()
const uploading = ref(false)
const message = useMessage()

// 上传大小上限（MB）——唯一出处，校验与提示文案均引用此常量
const MAX_UPLOAD_MB = 500
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

async function customRequest({ file, onFinish, onError }: UploadCustomRequestOptions) {
  if (file.file) {
    uploading.value = true
    try {
      const res = await api.upload(file.file)
      let taskId = res.task_id
      try {
        await api.startTranscribe(taskId)
      } catch {
        // transcribe 失败也能看到任务详情页，可手动重试
      }
      message.success('上传成功，正在转录...')
      router.push(`/transcript/${taskId}`)
      onFinish()
    } catch (e: any) {
      message.error(e.message || '上传失败')
      onError()
    } finally {
      uploading.value = false
    }
  } else {
    onError()
  }
}

function onBeforeUpload({ file }: { file: UploadFileInfo }) {
  if (file.file) {
    if (file.file.size > MAX_UPLOAD_BYTES) {
      message.error(`文件超过 ${MAX_UPLOAD_MB}MB 限制`)
      return false
    }
  }
  return true
}
</script>

<template>
  <div>
    <h1 style="font-size: 24px; margin-bottom: 8px;">上传音频文件</h1>
    <NText depth="3" style="font-size: 14px; display: block; margin-bottom: 24px;">
      支持 WAV, MP3, M4A, FLAC, OGG, WebM 等格式
    </NText>

    <NCard>
      <NSpin :show="uploading" description="上传中...">
        <NUpload
          :custom-request="customRequest"
          :show-file-list="false"
          :before-upload="onBeforeUpload"
          accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg,.webm,.opus,.aac,.wma"
        >
          <NUploadDragger>
            <div style="padding: 32px 16px; text-align: center;">
              <div style="font-size: 48px; color: #1a73e8; line-height: 1; margin-bottom: 12px;">+</div>
              <NText style="font-size: 15px;">点击或拖拽文件到此区域上传</NText>
              <br />
              <NText depth="3" style="font-size: 12px;">限 {{ MAX_UPLOAD_MB }}MB 以内</NText>
            </div>
          </NUploadDragger>
        </NUpload>
      </NSpin>
    </NCard>
  </div>
</template>
