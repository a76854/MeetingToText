<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { api } from '../api/client'


const DEFAULT_ASR_MODEL: Record<string, string> = {
  sensevoice: 'iic/SenseVoiceSmall',
  paraformer: 'iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
}

const activeTab = ref<'model' | 'record' | 'tuning'>('model')

const llmBaseUrl = ref('')
const llmApiKey = ref('')
const llmModel = ref('')
const llmTemperature = ref(0.3)
const llmMaxTokens = ref(4096)
const llmMaxInputTokens = ref(128000)
const asrModelType = ref('sensevoice')
const asrModelName = ref('iic/SenseVoiceSmall')
const asrNeedsPunc = ref(false)
const ncpu = ref(0)
const asrBatchSizeS = ref(300)
const asrMergeLengthS = ref(15)
const asrMergeVad = ref(true)
const asrMaxSingleSegmentTime = ref(60000)
const streamingAsrEnabled = ref(false)
const streamingAsrModelName = ref('paraformer-zh-streaming')
const noiseSuppression = ref(true)
const micEnabled = ref(true)
const systemAudioEnabled = ref(false)
const maxCpu = navigator.hardwareConcurrency || 16
const apiKeySet = ref(false)
const saved = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    const s = await api.getSettings()
    llmBaseUrl.value = s.llm_base_url
    llmModel.value = s.llm_model
    llmTemperature.value = s.llm_temperature
    llmMaxTokens.value = s.llm_max_tokens
    llmMaxInputTokens.value = s.llm_max_input_tokens
    asrModelType.value = s.asr_model_type
    asrModelName.value = s.asr_model_name || 'iic/SenseVoiceSmall'
    asrNeedsPunc.value = s.asr_needs_punc
    ncpu.value = s.ncpu
    asrBatchSizeS.value = s.asr_batch_size_s
    asrMergeLengthS.value = s.asr_merge_length_s
    asrMergeVad.value = s.asr_merge_vad
    asrMaxSingleSegmentTime.value = s.asr_max_single_segment_time
    streamingAsrEnabled.value = s.streaming_asr_enabled
    streamingAsrModelName.value = s.streaming_asr_model_name || 'paraformer-zh-streaming'
    noiseSuppression.value = s.browser_noise_suppression
    const source = s.audio_source || 'mic'
    micEnabled.value = source.includes('mic')
    systemAudioEnabled.value = source.includes('system')
    apiKeySet.value = s.llm_api_key_set
  } catch (e: any) {
    error.value = e.message
  }
})

watch(asrModelType, (newType) => {
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
  saved.value = false
  try {
    await api.updateSettings({
      llm_base_url: llmBaseUrl.value,
      llm_api_key: llmApiKey.value,
      llm_model: llmModel.value,
      llm_temperature: llmTemperature.value,
      llm_max_tokens: llmMaxTokens.value,
      llm_max_input_tokens: llmMaxInputTokens.value,
      asr_model_type: asrModelType.value,
      asr_model_name: asrModelName.value,
      asr_needs_punc: asrNeedsPunc.value,
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
    saved.value = true
    apiKeySet.value = apiKeySet.value || !!llmApiKey.value
    llmApiKey.value = ''
    setTimeout(() => { saved.value = false }, 3000)
  } catch (e: any) {
    error.value = e.message || '保存失败'
  }
}

async function clearApiKey() {
  if (!confirm('确认清除当前 API Key？清除后需重新填入才能生成纪要。')) return
  try {
    await api.deleteSetting('llm_api_key')
    apiKeySet.value = false
    saved.value = true
    setTimeout(() => { saved.value = false }, 3000)
  } catch (e: any) {
    error.value = e.message || '清除失败'
  }
}
</script>

<template>
  <div class="page">
    <h1>设置</h1>

    <div class="tabs">
      <button :class="['tab', { active: activeTab === 'model' }]" @click="activeTab = 'model'">模型设置</button>
      <button :class="['tab', { active: activeTab === 'tuning' }]" @click="activeTab = 'tuning'">识别调优</button>
      <button :class="['tab', { active: activeTab === 'record' }]" @click="activeTab = 'record'">录制设置</button>
    </div>

    <Transition name="fade" mode="out-in">
      <div v-if="activeTab === 'model'" key="model" class="tab-content">
        <div class="section">
          <h2>LLM 配置 (OpenAI API)</h2>
          <label class="field">
            <span>API 地址</span>
            <input v-model="llmBaseUrl" placeholder="https://api.deepseek.com" class="input" />
          </label>
          <label class="field">
            <span>
              API Key
              <span v-if="apiKeySet" class="badge">已设置</span>
            </span>
            <div class="key-row">
              <input v-model="llmApiKey" type="password" :placeholder="apiKeySet ? '留空保留原 Key' : 'sk-...'" class="input" />
              <button v-if="apiKeySet" class="btn-clear" @click="clearApiKey" title="清除已保存的 Key">清除</button>
            </div>
          </label>
          <label class="field">
            <span>模型</span>
            <input v-model="llmModel" placeholder="deepseek-chat" class="input" />
          </label>
          <div class="row-2">
            <label class="field">
              <span>温度 ({{ llmTemperature }})</span>
              <input v-model.number="llmTemperature" type="range" min="0" max="2" step="0.1" />
            </label>
            <label class="field">
              <span>最大输出 tokens</span>
              <input v-model.number="llmMaxTokens" type="number" min="256" max="32768" step="256" class="input" />
            </label>
          </div>
          <label class="field">
            <span>最大输入 tokens（超长转录将自动截断中间部分）</span>
            <input v-model.number="llmMaxInputTokens" type="number" min="1024" max="999999" step="1024" class="input" />
          </label>
        </div>

        <div class="section">
          <h2>语音识别配置</h2>
          <label class="field">
            <span>ASR 引擎（含内置说话人分离）</span>
            <select v-model="asrModelType" class="input">
              <option value="sensevoice">SenseVoice (轻量)</option>
              <option value="paraformer">Paraformer (更高精度)</option>
            </select>
          </label>
          <label class="field">
            <span>ASR 模型名 (ModelScope)</span>
            <input v-model="asrModelName" placeholder="iic/SenseVoiceSmall" class="input" />
          </label>
        </div>

        <div class="section">
          <h2>实时转录</h2>
          <label class="field checkbox-field">
            <input v-model="streamingAsrEnabled" type="checkbox" />
            <span>启用服务端实时转录</span>
          </label>
          <label v-if="streamingAsrEnabled" class="field">
            <span>流式 ASR 模型名</span>
            <input v-model="streamingAsrModelName" placeholder="paraformer-zh-streaming" class="input" />
          </label>
        </div>
      </div>

      <div v-else-if="activeTab === 'tuning'" key="tuning" class="tab-content">
        <div class="section">
          <h2>计算资源</h2>
          <label class="field">
            <span>CPU 线程数 (0=自动, {{ ncpu }})</span>
            <input v-model.number="ncpu" type="range" min="0" :max="maxCpu" step="1" />
            <span class="hint">当前可用 {{ maxCpu }} 核，0 表示全部使用</span>
          </label>
        </div>

        <div class="section">
          <h2>识别参数</h2>
          <div class="row-2">
            <label class="field">
              <span>批处理时长 (秒)</span>
              <input v-model.number="asrBatchSizeS" type="number" min="30" max="600" step="30" class="input" />
              <span class="hint">越大越快，占更多内存</span>
            </label>
            <label class="field">
              <span>VAD 单段最大时长 (毫秒)</span>
              <input v-model.number="asrMaxSingleSegmentTime" type="number" min="10000" max="120000" step="5000" class="input" />
              <span class="hint">单段超时自动切分</span>
            </label>

          </div>
          <div class="row-2">
            <label class="field">
              <span>VAD 合并阈值 (秒)</span>
              <input v-model.number="asrMergeLengthS" type="number" min="1" max="30" step="1" class="input" />
              <span class="hint">相邻语音段多近合并</span>
            </label>
            <label class="field checkbox-field">
              <input v-model="asrMergeVad" type="checkbox" />
              <span>合并 VAD 相邻段</span>
            </label>
          </div>
        </div>
      </div>

      <div v-else key="record" class="tab-content">
        <div class="section">
          <h2>音频源</h2>
          <label class="field checkbox-field">
            <input v-model="micEnabled" type="checkbox" />
            <span>麦克风</span>
          </label>
          <label class="field checkbox-field">
            <input v-model="systemAudioEnabled" type="checkbox" />
            <span>系统音频</span>
          </label>
          <p v-if="systemAudioEnabled" class="hint-text">点击开始录音后浏览器会弹出共享对话框，请选择「整个屏幕」并勾选「共享系统音频」</p>
        </div>

        <div class="section">
          <h2>音频处理</h2>
          <label class="field checkbox-field">
            <input v-model="noiseSuppression" type="checkbox" />
            <span>浏览器降噪（回声消除、降噪、自动增益）</span>
          </label>
        </div>
      </div>
    </Transition>

    <button class="btn-save" @click="saveSettings">保存设置</button>

    <Transition name="toast">
      <div v-if="saved" class="toast">设置已保存</div>
    </Transition>
    <div v-if="error" class="error-box">{{ error }}</div>
  </div>
</template>

<style scoped>
.page { max-width: 600px; margin: 0 auto; }
h1 { font-size: 24px; margin-bottom: 16px; }

.tabs {
  display: flex;
  gap: 0;
  margin-bottom: 16px;
  border-bottom: 2px solid #e0e0e0;
}
.tab {
  padding: 10px 20px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 14px;
  color: #888;
  position: relative;
  font-family: inherit;
}
.tab.active {
  color: #1a73e8;
  font-weight: 500;
}
.tab.active::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  right: 0;
  height: 2px;
  background: #1a73e8;
}

.tab-content { min-height: 0; }

.section {
  background: white;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
h2 { font-size: 16px; margin-bottom: 14px; color: #333; }

.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.field span { font-size: 13px; color: #666; }
.checkbox-field {
  flex-direction: row;
  align-items: flex-start;
  gap: 10px;
  margin-top: 32px;
  cursor: pointer;
}
.checkbox-field input[type="checkbox"] {
  width: 18px;
  height: 18px;
  margin-top: 1px;
  cursor: pointer;
}
.checkbox-field span { flex: 1; line-height: 1.5; }

.hint-text { font-size: 12px; color: #e65c00; margin-top: -8px; margin-bottom: 8px; line-height: 1.5; }

.row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 640px) {
  .row-2 { grid-template-columns: 1fr; }
}

.badge {
  font-size: 11px;
  color: #137333;
  background: #e6f4ea;
  padding: 1px 6px;
  border-radius: 3px;
  margin-left: 6px;
}

.input {
  padding: 10px 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
}
.input:focus { outline: none; border-color: #1a73e8; }

.key-row { display: flex; gap: 8px; }
.key-row .input { flex: 1; }
.btn-clear {
  padding: 0 12px;
  background: white;
  border: 1px solid #f4c2c0;
  color: #d93025;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
}
.btn-clear:hover { background: #fce8e6; }

.btn-save {
  width: 100%;
  padding: 14px;
  background: #1a73e8;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  cursor: pointer;
}
.btn-save:hover { background: #1557b0; }

.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; margin-top: 12px; }

.toast {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  padding: 12px 24px;
  background: #137333;
  color: white;
  border-radius: 24px;
  font-size: 14px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  z-index: 1000;
  pointer-events: none;
}
.toast-enter-active, .toast-leave-active { transition: opacity 0.2s, transform 0.2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(-8px); }

.fade-enter-active, .fade-leave-active { transition: opacity 0.15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 640px) {
  .page { max-width: 100%; }
  h1 { font-size: 20px; }
  .section { padding: 16px; }
  .input { font-size: 16px; }
}
</style>
