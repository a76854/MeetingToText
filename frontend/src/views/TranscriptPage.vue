<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard,
  NButton,
  NSpace,
  NTag,
  NSpin,
  NAlert,
  NEmpty,
  NSlider,
  NDivider,
  useDialog,
  useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { formatDuration } from '../utils/format'
import { downloadUrl } from '../utils/download'
import ProgressIndicator from '../components/ProgressIndicator.vue'

const route = useRoute()
const router = useRouter()
const dialog = useDialog()
const message = useMessage()

const taskId = route.params.taskId as string
const loading = ref(true)
const status = ref('')
const segments = ref<any[]>([])
const fullText = ref('')
const duration = ref(0)
const progress = ref<any>(null)
const error = ref('')
const pipelineError = ref('')
const playingId = ref<string | null>(null)
const audioCurrentTime = ref(0)
const audioDuration = ref(0)
const audioPlayer = ref<HTMLAudioElement | null>(null)
let audioEventsAttached = false

let es: EventSource | null = null
let isUnmounted = false

onMounted(async () => {
  await loadTask()
  if (status.value === 'processing' || status.value === 'pending') {
    subscribeProgress()
  }
  loading.value = false
})

onUnmounted(() => {
  isUnmounted = true
  if (es) es.close()
})

async function loadTask() {
  try {
    const data = await api.getTranscript(taskId)
    status.value = data.status
    segments.value = (data.segments || []).map((s: any) => ({ ...s }))
    fullText.value = data.full_text
    duration.value = data.duration
    pipelineError.value = data.error || ''
  } catch (e: any) {
    error.value = e.message || '加载失败'
  }
}

function subscribeProgress() {
  if (isUnmounted) return
  es = api.streamProgress(
    taskId,
    (t) => {
      progress.value = t.progress
      status.value = t.status
    },
    (t) => {
      status.value = t.status
      segments.value = (t.result?.segments || []).map((s: any) => ({ ...s }))
      fullText.value = t.result?.full_text || ''
      duration.value = t.result?.duration || 0
      pipelineError.value = t.error || ''
      progress.value = null
    },
    (e) => {
      error.value = e
      progress.value = null
    },
  )
}

function goToGenerate() {
  router.push(`/generate/${taskId}`)
}

function goToMinutes() {
  router.push(`/minutes/${taskId}`)
}

function goToEdit() {
  router.push(`/edit/${taskId}`)
}

function deleteTask() {
  dialog.warning({
    title: '确认删除',
    content: '此任务的音频和转录将一并清除，不可恢复。',
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.deleteTask(taskId)
        message.success('已删除')
        router.push('/tasks')
      } catch (e: any) {
        message.error(e.message || '删除失败')
      }
    },
  })
}

function exportAs(format: string) {
  downloadUrl(api.exportUrl(taskId, format))
}

function togglePlay() {
  const audio = audioPlayer.value
  if (!audio) return
  initAudioEvents()
  if (audio.paused) {
    audio.play().then(() => { playingId.value = 'play' }).catch(() => {})
  } else {
    audio.pause()
    playingId.value = null
  }
}

function initAudioEvents() {
  if (audioEventsAttached) return
  const audio = audioPlayer.value
  if (!audio) return
  if (audio.duration && isFinite(audio.duration)) {
    audioDuration.value = audio.duration
  }
  audio.addEventListener('timeupdate', () => {
    audioCurrentTime.value = audio.currentTime
  })
  audio.addEventListener('loadedmetadata', () => {
    audioDuration.value = audio.duration
  })
  audio.addEventListener('ended', () => {
    playingId.value = null
    audioCurrentTime.value = 0
  })
  audioEventsAttached = true
}

function onSeekChange(value: number) {
  const audio = audioPlayer.value
  if (!audio) return
  initAudioEvents()
  audio.currentTime = value
}

function retryTranscribe() {
  dialog.warning({
    title: '重新转录',
    content: '当前转录结果将被覆盖。',
    positiveText: '确认重转',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.retryTranscribe(taskId)
        status.value = 'pending'
        segments.value = []
        fullText.value = ''
        progress.value = null
        subscribeProgress()
        message.success('已开始重新转录')
      } catch (e: any) {
        message.error(e.message || '重新转录失败')
      }
    },
  })
}
</script>

<template>
  <div>
    <NSpace align="center" justify="space-between" style="margin-bottom: 16px; flex-wrap: wrap;" :wrap-item="false">
      <h1 style="font-size: 24px; margin: 0;">转录结果</h1>
      <NSpace align="center" v-if="status === 'processing'">
        <NTag type="warning" round>转写中...</NTag>
      </NSpace>
    </NSpace>

    <NCard v-if="status === 'done'" style="margin-bottom: 16px;">
      <NSpace vertical :size="16">
        <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap; width: 100%;">
          <div style="display: flex; align-items: center; gap: 16px; flex: 1; min-width: 300px;">
            <NButton @click="togglePlay" type="primary" ghost>
              {{ playingId ? '暂停' : '播放' }}
            </NButton>
            <div style="display: flex; align-items: center; gap: 8px; flex: 1; min-width: 120px;">
              <span style="font-size: 12px; color: #666; font-variant-numeric: tabular-nums; min-width: 40px; text-align: right;">
                {{ formatDuration(audioCurrentTime) }}
              </span>
              <NSlider
                :value="audioCurrentTime"
                :min="0"
                :max="audioDuration || 0"
                :step="0.1"
                :tooltip="false"
                style="flex: 1;"
                @update:value="onSeekChange"
              />
              <span style="font-size: 12px; color: #666; font-variant-numeric: tabular-nums; min-width: 40px;">
                {{ formatDuration(audioDuration) }}
              </span>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <NButton @click="retryTranscribe" secondary>重转</NButton>
            <NButton @click="goToEdit" secondary>编辑</NButton>
          </div>
        </div>
        <NDivider style="margin: 0;" />
        <NSpace align="center" justify="space-between" wrap>
          <NSpace align="center">
            <span style="font-size: 13px; color: #888;">导出：</span>
            <NButton size="small" @click="exportAs('txt')">TXT</NButton>
            <NButton size="small" @click="exportAs('srt')">SRT 字幕</NButton>
            <NButton size="small" @click="exportAs('md')">Markdown</NButton>
          </NSpace>
          <NSpace>
            <NButton @click="goToMinutes" ghost>查看纪要</NButton>
            <NButton @click="goToGenerate" type="primary">生成纪要</NButton>
            <NButton @click="deleteTask" type="error" ghost>删除任务</NButton>
          </NSpace>
        </NSpace>
      </NSpace>
    </NCard>

    <NAlert v-if="error" type="error" :title="error" style="margin-bottom: 16px;" />

    <div v-if="status === 'processing' || status === 'pending'">
      <NCard>
        <ProgressIndicator v-if="progress" :progress="progress" />
        <NSpin v-else>
          <div style="text-align: center; padding: 24px;">正在处理转写，请稍候...</div>
        </NSpin>
      </NCard>
    </div>

    <NCard v-else-if="status === 'error'" style="text-align: center;">
      <NEmpty :description="pipelineError || '转写出错'">
        <template #extra>
          <NSpace>
            <NButton @click="retryTranscribe" type="primary">重新转录</NButton>
            <NButton @click="deleteTask" type="error" ghost>删除任务</NButton>
          </NSpace>
        </template>
      </NEmpty>
    </NCard>

    <template v-else-if="status === 'done'">
      <NCard>
        <template v-if="segments.length">
          <NSpace vertical :size="10">
            <NCard
              v-for="(seg, i) in segments"
              :key="i"
              size="small"
              hoverable
            >
              <NSpace align="center" justify="space-between" style="margin-bottom: 6px;">
                <NTag :type="seg.speaker ? 'info' : 'default'" size="small" round>
                  {{ seg.speaker || '未知说话人' }}
                </NTag>
                <span style="font-size: 12px; color: #aaa; font-variant-numeric: tabular-nums;">
                  {{ formatDuration(seg.start) }} - {{ formatDuration(seg.end) }}
                </span>
              </NSpace>
              <div style="font-size: 15px; line-height: 1.6;">{{ seg.text }}</div>
            </NCard>
          </NSpace>
        </template>
        <pre v-else-if="fullText" style="white-space: pre-wrap; font-family: inherit; font-size: 15px; line-height: 1.8; margin: 0;">{{ fullText }}</pre>
        <NEmpty
          v-else
          :description="pipelineError || '转录完成，但未能识别到语音内容。请检查麦克风是否正常工作后重新录制。'"
        />
      </NCard>



      <audio ref="audioPlayer" :src="api.audioUrl(taskId)" style="display: none;"></audio>
    </template>
  </div>
</template>
