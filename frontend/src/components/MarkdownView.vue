<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import { sanitizeHtml } from '../utils/sanitize'

/**
 * Shared markdown renderer (single source of truth for DUP7).
 * Owns: marked options, markdown -> sanitized HTML conversion, and the
 * .minutes-content typography CSS. XSS guard: output is always passed
 * through DOMPurify via sanitizeHtml before v-html.
 */
const props = defineProps<{ source: string }>()

marked.setOptions({ breaks: true, gfm: true })

const html = computed(() => props.source ? sanitizeHtml(props.source) : '')
</script>

<template>
  <div class="minutes-content" v-html="html" />
</template>

<style scoped>
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
</style>
