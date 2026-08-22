import DOMPurify from 'dompurify'
import { marked } from 'marked'

/**
 * Parse untrusted markdown (e.g. LLM-generated meeting minutes) to HTML and
 * sanitize it with DOMPurify so it is safe to render via v-html.
 *
 * Strips <script>, event handlers (onerror/onclick/...), javascript: URLs, etc.
 * while preserving normal markdown output (headings, bold, lists, tables, code).
 */
export function sanitizeHtml(md: string): string {
  return DOMPurify.sanitize(marked.parse(md) as string)
}
