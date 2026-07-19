<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api/client'

const llmBaseUrl = ref('')
const llmApiKey = ref('')
const llmModel = ref('')
const asrModelType = ref('sensevoice')
const saved = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    const s = await api.getSettings()
    llmBaseUrl.value = s.llm_base_url
    llmModel.value = s.llm_model
    asrModelType.value = s.asr_model_type
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
      asr_model_type: asrModelType.value,
    })
    saved.value = true
    setTimeout(() => { saved.value = false }, 3000)
  } catch (e: any) {
    error.value = e.message || '保存失败'
  }
}
</script>

<template>
  <div class="page">
    <h1>设置</h1>

    <div class="section">
      <h2>LLM 配置</h2>
      <label class="field">
        <span>API 地址</span>
        <input v-model="llmBaseUrl" placeholder="https://api.deepseek.com" class="input" />
      </label>
      <label class="field">
        <span>API Key</span>
        <input v-model="llmApiKey" type="password" placeholder="sk-..." class="input" />
      </label>
      <label class="field">
        <span>模型</span>
        <input v-model="llmModel" placeholder="deepseek-chat" class="input" />
      </label>
    </div>

    <div class="section">
      <h2>语音识别配置</h2>
      <label class="field">
        <span>ASR 引擎（含内置说话人分离）</span>
        <select v-model="asrModelType" class="input">
          <option value="sensevoice">SenseVoice (推荐，轻量)</option>
          <option value="paraformer">Paraformer (更高精度)</option>
        </select>
      </label>
    </div>

    <button class="btn-save" @click="saveSettings">保存设置</button>

    <div v-if="saved" class="success-box">设置已保存</div>
    <div v-if="error" class="error-box">{{ error }}</div>
  </div>
</template>

<style scoped>
.page { max-width: 560px; margin: 0 auto; }
h1 { font-size: 24px; margin-bottom: 24px; }

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

.input {
  padding: 10px 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
}
.input:focus { outline: none; border-color: #1a73e8; }

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
</style>
