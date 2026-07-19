<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import { api } from '../api/client'

const route = useRoute()
const taskId = route.params.taskId as string

const templates = ref<any[]>([])
const selectedTemplate = ref('meeting_minutes')
const customInstructions = ref('')
const generating = ref(false)
const minutes = ref('')
const error = ref('')

marked.setOptions({ breaks: true, gfm: true })

onMounted(async () => {
  try {
    const res = await api.getTemplates()
    templates.value = res.templates
  } catch (e: any) {
    error.value = e.message
  }
})

async function doGenerate() {
  generating.value = true
  error.value = ''
  try {
    const res = await api.generateMinutes(taskId, selectedTemplate.value, customInstructions.value)
    minutes.value = res.minutes
  } catch (e: any) {
    error.value = e.message || '生成失败'
  } finally {
    generating.value = false
  }
}

const minutesHtml = computed(() => minutes.value ? marked.parse(minutes.value) as string : '')

function copyToClipboard() {
  navigator.clipboard.writeText(minutes.value)
}

function downloadMarkdown() {
  const url = api.exportUrl(taskId, 'md')
  fetch(url).then(r => r.blob()).then(blob => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = ''
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(a.href)
  })
}
</script>

<template>
  <div class="page">
    <h1>生成会议纪要</h1>

    <div class="form-section">
      <label class="field-label">选择模板</label>
      <div class="template-list">
        <div
          v-for="t in templates" :key="t.id"
          class="template-card"
          :class="{ selected: selectedTemplate === t.id }"
          @click="selectedTemplate = t.id"
        >
          <div class="t-name">{{ t.name }}</div>
          <div class="t-desc">{{ t.description }}</div>
        </div>
      </div>
    </div>

    <div class="form-section">
      <label class="field-label" for="customInstr">额外要求（选填）</label>
      <textarea id="customInstr" v-model="customInstructions" placeholder="例如：使用英文输出、重点提取技术讨论内容..." rows="3" class="input-field" />
    </div>

    <button class="btn-generate" @click="doGenerate" :disabled="generating">
      {{ generating ? '生成中...' : '生成会议纪要' }}
    </button>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="minutes" class="minutes-output">
      <div class="minutes-header">
        <span>生成结果</span>
        <div class="minutes-actions">
          <button class="btn-mini" @click="downloadMarkdown" title="下载 Markdown（包含转录）">下载 .md</button>
          <button class="btn-mini" @click="copyToClipboard">复制</button>
        </div>
      </div>
      <div class="minutes-content" v-html="minutesHtml" />
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 700px; margin: 0 auto; }
h1 { font-size: 24px; margin-bottom: 24px; }

.form-section { margin-bottom: 20px; }
.field-label { display: block; font-size: 14px; font-weight: 600; margin-bottom: 10px; color: #444; }

.template-list { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.template-card {
  padding: 14px;
  border: 2px solid #e0e0e0;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  background: white;
}
.template-card:hover { border-color: #1a73e8; }
.template-card.selected { border-color: #1a73e8; background: #f0f6ff; }
.t-name { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.t-desc { font-size: 12px; color: #888; }

.input-field {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
}
.input-field:focus { outline: none; border-color: #1a73e8; }

.btn-generate {
  width: 100%;
  padding: 14px;
  background: #1a73e8;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  cursor: pointer;
  margin-bottom: 16px;
}
.btn-generate:hover { background: #1557b0; }
.btn-generate:disabled { opacity: 0.6; cursor: not-allowed; }

.minutes-output {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
.minutes-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #eee;
  font-weight: 600;
}
.minutes-actions { display: flex; gap: 8px; }
.btn-mini {
  padding: 6px 12px;
  background: #f0f0f0;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: #444;
}
.btn-mini:hover { background: #e0e0e0; }

.minutes-content {
  font-size: 15px;
  line-height: 1.8;
}
.minutes-content :deep(h1) { font-size: 22px; margin: 18px 0 10px; border-bottom: 1px solid #eee; padding-bottom: 6px; }
.minutes-content :deep(h2) { font-size: 18px; margin: 16px 0 8px; }
.minutes-content :deep(h3) { font-size: 16px; margin: 12px 0 6px; }
.minutes-content :deep(h4) { font-size: 15px; margin: 10px 0 4px; }
.minutes-content :deep(p) { margin: 8px 0; }
.minutes-content :deep(ul),
.minutes-content :deep(ol) { padding-left: 24px; margin: 8px 0; }
.minutes-content :deep(li) { margin: 4px 0; }
.minutes-content :deep(strong) { font-weight: 600; }
.minutes-content :deep(code) { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; font-size: 13px; }
.minutes-content :deep(pre) { background: #f5f5f5; padding: 12px; border-radius: 6px; overflow-x: auto; }
.minutes-content :deep(blockquote) { border-left: 3px solid #ddd; padding-left: 12px; color: #666; margin: 8px 0; }
.minutes-content :deep(table) { border-collapse: collapse; margin: 8px 0; width: 100%; }
.minutes-content :deep(th),
.minutes-content :deep(td) { border: 1px solid #ddd; padding: 6px 10px; }
.minutes-content :deep(th) { background: #f7f7f7; }

.error-box { padding: 12px; background: #fce8e6; border-radius: 8px; color: #d93025; margin-bottom: 16px; }
</style>
