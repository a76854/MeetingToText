<script setup lang="ts">
import { ref, onMounted, computed, watch, nextTick } from 'vue'
import {
  NCard,
  NTabPane,
  NTabs,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSwitch,
  NSlider,
  NButton,
  NSpace,
  NTag,
  NAlert,
  useMessage,
} from 'naive-ui'
import { api } from '../api/client'


const DEFAULT_ASR_MODEL: Record<string, string> = {
  sensevoice: 'iic/SenseVoiceSmall',
  paraformer: 'iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
}

const asrModelTypeOptions = [
  { label: 'SenseVoice (轻量)', value: 'sensevoice' },
  { label: 'Paraformer (更高精度)', value: 'paraformer' },
]

const message = useMessage()

// C7: refs start neutral — real values load from GET /api/settings on mount,
// whose defaults derive from backend/app/config.py. Do not re-hardcode
// config defaults here; config.py is the single source of truth.
const llmBaseUrl = ref('')
const llmApiKey = ref('')
const llmModel = ref('')
const llmTemperature = ref(0)
const llmMaxTokens = ref(0)
const asrModelType = ref('')
const asrModelName = ref('')
const asrNeedsPunc = ref(false)
const ncpu = ref(0)
const asrBatchSizeS = ref(0)
const asrMergeLengthS = ref(0)
const asrMergeVad = ref(false)
const asrMaxSingleSegmentTime = ref(0)
const streamingAsrEnabled = ref(false)
const streamingAsrModelName = ref('')
const noiseSuppression = ref(false)
const micEnabled = ref(false)
const systemAudioEnabled = ref(false)
const CPU_FALLBACK = 16
const maxCpu = navigator.hardwareConcurrency || CPU_FALLBACK
const apiKeySet = ref(false)
const saving = ref(false)
const error = ref('')

// Guard for the programmatic settings load below. watch(asrModelType) uses
// Vue's default flush: 'pre', which QUEUES its callback instead of running it
// synchronously — the job is flushed in a later microtask, i.e. AFTER the
// synchronous assignment block inside onMounted completes. Without this flag,
// loading a saved custom asr_model_name / asr_needs_punc would be immediately
// clobbered by the watcher's hardcoded defaults.
let isLoadingSettings = false

onMounted(async () => {
  isLoadingSettings = true
  try {
    const s = await api.getSettings()
    llmBaseUrl.value = s.llm_base_url
    llmModel.value = s.llm_model
    llmTemperature.value = s.llm_temperature
    llmMaxTokens.value = s.llm_max_tokens
    asrModelType.value = s.asr_model_type
    asrModelName.value = s.asr_model_name
    asrNeedsPunc.value = s.asr_needs_punc
    ncpu.value = s.ncpu
    asrBatchSizeS.value = s.asr_batch_size_s
    asrMergeLengthS.value = s.asr_merge_length_s
    asrMergeVad.value = s.asr_merge_vad
    asrMaxSingleSegmentTime.value = s.asr_max_single_segment_time
    streamingAsrEnabled.value = s.streaming_asr_enabled
    streamingAsrModelName.value = s.streaming_asr_model_name
    noiseSuppression.value = s.browser_noise_suppression
    const source = s.audio_source
    micEnabled.value = source.includes('mic')
    systemAudioEnabled.value = source.includes('system')
    apiKeySet.value = s.llm_api_key_set
    // Wait until the pending pre-flush watcher queue (queued by the
    // asrModelType assignment above) has drained before re-enabling the
    // watcher. nextTick() resolves only after flushJobs runs the queued
    // watcher callback, so the guard is guaranteed to still be `true` when
    // that callback executes.
    await nextTick()
  } catch (e: any) {
    error.value = e.message
  } finally {
    isLoadingSettings = false
  }
})

watch(asrModelType, (newType) => {
  // UI-display only: mirrors what the backend will derive on save
  // (settings.py POST: asr_needs_punc = (model_type == "paraformer")).
  // The SAVE payload must NOT send asr_needs_punc — the backend setdefault
  // is the sole authority, so this value is never persisted from here.
  // Only auto-derive model name / punc when the USER switches the engine
  // select. During programmatic load (onMounted) the saved values must win,
  // so skip the default-override entirely.
  if (isLoadingSettings) return
  const name = DEFAULT_ASR_MODEL[newType]
  if (name) asrModelName.value = name
  asrNeedsPunc.value = newType === 'paraformer'
})

const audioSourceValue = computed(() => {
  const parts: string[] = []
  if (micEnabled.value) parts.push('mic')
  if (systemAudioEnabled.value) parts.push('system')
  return parts.join(',') || 'mic'
})

async function saveSettings() {
  error.value = ''
  saving.value = true
  try {
    await api.updateSettings({
      llm_base_url: llmBaseUrl.value,
      llm_api_key: llmApiKey.value,
      llm_model: llmModel.value,
      llm_temperature: llmTemperature.value,
      llm_max_tokens: llmMaxTokens.value,
      asr_model_type: asrModelType.value,
      asr_model_name: asrModelName.value,
      // C8: asr_needs_punc deliberately omitted — backend derives it from
      // asr_model_type (settings.py POST setdefault) and is authoritative.
      ncpu: ncpu.value,
      asr_batch_size_s: asrBatchSizeS.value,
      asr_merge_length_s: asrMergeLengthS.value,
      asr_merge_vad: asrMergeVad.value,
      asr_max_single_segment_time: asrMaxSingleSegmentTime.value,
      streaming_asr_enabled: streamingAsrEnabled.value,
      streaming_asr_model_name: streamingAsrModelName.value,
      browser_noise_suppression: noiseSuppression.value,
      audio_source: audioSourceValue.value,
    })
    apiKeySet.value = apiKeySet.value || !!llmApiKey.value
    llmApiKey.value = ''
    message.success('设置已保存')
  } catch (e: any) {
    error.value = e.message || '保存失败'
    message.error(error.value)
  } finally {
    saving.value = false
  }
}

async function clearApiKey() {
  try {
    await api.deleteSetting('llm_api_key')
    apiKeySet.value = false
    message.success('API Key 已清除')
  } catch (e: any) {
    message.error(e.message || '清除失败')
  }
}
</script>

<template>
  <div>
    <h1 style="font-size: 24px; margin-bottom: 16px;">
      设置
    </h1>

    <NTabs
      type="line"
      animated
    >
      <NTabPane
        name="model"
        tab="模型设置"
      >
        <NSpace
          vertical
          :size="16"
        >
          <NCard title="LLM 配置 (OpenAI API)">
            <NForm
              label-placement="top"
              :show-feedback="false"
            >
              <NFormItem label="API 地址">
                <NInput
                  v-model:value="llmBaseUrl"
                  placeholder="https://api.deepseek.com"
                />
              </NFormItem>
              <NFormItem>
                <template #label>
                  <NSpace
                    align="center"
                    :size="8"
                  >
                    <span>API Key</span>
                    <NTag
                      v-if="apiKeySet"
                      type="success"
                      size="small"
                      round
                    >
                      已设置
                    </NTag>
                  </NSpace>
                </template>
                <NSpace
                  :size="8"
                  style="width: 100%;"
                >
                  <NInput
                    v-model:value="llmApiKey"
                    type="password"
                    show-password-on="click"
                    :placeholder="apiKeySet ? '留空保留原 Key' : 'sk-...'"
                    style="flex: 1;"
                  />
                  <NButton
                    v-if="apiKeySet"
                    type="warning"
                    ghost
                    @click="clearApiKey"
                  >
                    清除
                  </NButton>
                </NSpace>
              </NFormItem>
              <NFormItem label="模型">
                <NInput
                  v-model:value="llmModel"
                  placeholder="deepseek-chat"
                />
              </NFormItem>
              <NFormItem :label="`温度 (${llmTemperature})`">
                <NSlider
                  v-model:value="llmTemperature"
                  :min="0"
                  :max="2"
                  :step="0.1"
                  :marks="{ 0: '0', 1: '1', 2: '2' }"
                />
              </NFormItem>
              <NFormItem label="最大输出 tokens">
                <NInputNumber
                  v-model:value="llmMaxTokens"
                  :min="256"
                  :max="32768"
                  :step="256"
                  style="width: 100%;"
                />
              </NFormItem>
            </NForm>
          </NCard>

          <NCard title="语音识别配置">
            <NForm
              label-placement="top"
              :show-feedback="false"
            >
              <NFormItem label="ASR 引擎（含内置说话人分离）">
                <NSelect
                  v-model:value="asrModelType"
                  :options="asrModelTypeOptions"
                />
              </NFormItem>
              <NFormItem label="ASR 模型名 (ModelScope)">
                <NInput
                  v-model:value="asrModelName"
                  placeholder="iic/SenseVoiceSmall"
                />
              </NFormItem>
            </NForm>
          </NCard>

          <NCard title="实时转录">
            <NForm
              label-placement="top"
              :show-feedback="false"
            >
              <NFormItem>
                <NSpace align="center">
                  <NSwitch v-model:value="streamingAsrEnabled" />
                  <span>启用服务端实时转录</span>
                </NSpace>
              </NFormItem>
              <NFormItem
                v-if="streamingAsrEnabled"
                label="流式 ASR 模型名"
              >
                <NInput
                  v-model:value="streamingAsrModelName"
                  placeholder="paraformer-zh-streaming"
                />
              </NFormItem>
            </NForm>
          </NCard>
        </NSpace>
      </NTabPane>

      <NTabPane
        name="tuning"
        tab="识别调优"
      >
        <NSpace
          vertical
          :size="16"
        >
          <NCard title="计算资源">
            <NForm
              label-placement="top"
              :show-feedback="false"
            >
              <NFormItem :label="`CPU 线程数 (0=自动, ${ncpu})`">
                <NSpace
                  vertical
                  style="width: 100%;"
                >
                  <NSlider
                    v-model:value="ncpu"
                    :min="0"
                    :max="maxCpu"
                    :step="1"
                    :marks="{ 0: '0', [maxCpu]: String(maxCpu) }"
                  />
                  <span style="font-size: 12px; color: #888;">当前可用 {{ maxCpu }} 核，0 表示全部使用</span>
                </NSpace>
              </NFormItem>
            </NForm>
          </NCard>

          <NCard title="识别参数">
            <NForm
              label-placement="top"
              :show-feedback="false"
            >
              <NFormItem label="批处理时长 (秒)">
                <NInputNumber
                  v-model:value="asrBatchSizeS"
                  :min="30"
                  :max="600"
                  :step="30"
                  style="width: 100%;"
                />
                <span style="font-size: 12px; color: #888;">越大越快，占更多内存</span>
              </NFormItem>
              <NFormItem label="VAD 单段最大时长 (毫秒)">
                <NInputNumber
                  v-model:value="asrMaxSingleSegmentTime"
                  :min="10000"
                  :max="120000"
                  :step="5000"
                  style="width: 100%;"
                />
                <span style="font-size: 12px; color: #888;">单段超时自动切分</span>
              </NFormItem>
              <NFormItem label="VAD 合并阈值 (秒)">
                <NInputNumber
                  v-model:value="asrMergeLengthS"
                  :min="1"
                  :max="30"
                  :step="1"
                  style="width: 100%;"
                />
                <span style="font-size: 12px; color: #888;">相邻语音段多近合并</span>
              </NFormItem>
              <NFormItem>
                <NSpace align="center">
                  <NSwitch v-model:value="asrMergeVad" />
                  <span>合并 VAD 相邻段</span>
                </NSpace>
              </NFormItem>
            </NForm>
          </NCard>
        </NSpace>
      </NTabPane>

      <NTabPane
        name="record"
        tab="录制设置"
      >
        <NSpace
          vertical
          :size="16"
        >
          <NCard title="音频源">
            <NSpace vertical>
              <NSpace align="center">
                <NSwitch v-model:value="micEnabled" />
                <span>麦克风</span>
              </NSpace>
              <NSpace align="center">
                <NSwitch v-model:value="systemAudioEnabled" />
                <span>系统音频</span>
              </NSpace>
              <NAlert
                v-if="systemAudioEnabled"
                type="warning"
                title="提示"
                :show-icon="false"
              >
                点击开始录音后浏览器会弹出共享对话框，请选择「整个屏幕」并勾选「共享系统音频」
              </NAlert>
            </NSpace>
          </NCard>

          <NCard title="音频处理">
            <NSpace align="center">
              <NSwitch v-model:value="noiseSuppression" />
              <span>浏览器降噪（回声消除、降噪、自动增益）</span>
            </NSpace>
          </NCard>
        </NSpace>
      </NTabPane>
    </NTabs>

    <div style="margin-top: 24px;">
      <NButton
        type="primary"
        size="large"
        block
        :loading="saving"
        @click="saveSettings"
      >
        保存设置
      </NButton>
    </div>
  </div>
</template>
