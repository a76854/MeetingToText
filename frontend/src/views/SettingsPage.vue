<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api/client'

const llmBaseUrl = ref('')
const llmApiKey = ref('')
const llmModel = ref('')
const llmTemperature = ref(0.3)
const llmMaxTokens = ref(4096)
const asrModelType = ref('sensevoice')
const asrModelName = ref('iic/SenseVoiceSmall')
const streamingAsrEnabled = ref(false)
const streamingAsrModelName = ref('paraformer-zh-streaming')
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
    asrModelType.value = s.asr_model_type
    asrModelName.value = s.asr_model_name || 'iic/SenseVoiceSmall'
    streamingAsrEnabled.value = s.streaming_asr_enabled
    streamingAsrModelName.value = s.streaming_asr_model_name || 'paraformer-zh-streaming'
    apiKeySet.value = s.llm_api_key_set
  } catch (e: any) {
    error.value = e.message
  }
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
      asr_model_type: asrModelType.value,
      asr_model_name: asrModelName.value,
      streaming_asr_enabled: streamingAsrEnabled.value,
      streaming_asr_model_name: streamingAsrModelName.value,
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

    <div class="section">
      <h2>LLM 配置(openai api)</h2>
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

    <button class="btn-save" @click="saveSettings">保存设置</button>

    <div v-if="saved" class="success-box">设置已保存</div>
    <div v-if="error" class="error-box">{{ error }}</div>
  </div>
</template>

<style scoped>
.page { max-width: 600px; margin: 0 auto; }
h1 { font-size: 24px; margin-bottom: 8px; }
.hint { font-size: 12px; color: #888; margin-bottom: 20px; }
.hint code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; font-size: 11px; }

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
  cursor: pointer;
}
.checkbox-field input[type="checkbox"] {
  width: 18px;
  height: 18px;
  margin-top: 1px;
  cursor: pointer;
}
.checkbox-field span {
  flex: 1;
  line-height: 1.5;
}
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

.success-box { padding: 12px; background: #e6f4ea; border-radius: 8px; color: #137333; margin-top: 12px; }
.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; margin-top: 12px; }

@media (max-width: 640px) {
  .page { max-width: 100%; }
  h1 { font-size: 20px; }
  .section { padding: 16px; }
  .input { font-size: 16px; }  /* 防止 iOS 自动放大 */
}
</style>
