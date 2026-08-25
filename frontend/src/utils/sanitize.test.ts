import { describe, it, expect } from 'vitest'
import { sanitizeHtml } from './sanitize'

describe('sanitizeHtml', () => {
  it('strips <script> tags and their content', () => {
    const out = sanitizeHtml('<script>alert(1)</script>')
    expect(out).not.toContain('<script>')
    expect(out).not.toContain('alert(1)')
  })

  it('strips event-handler attributes like onerror', () => {
    const out = sanitizeHtml('<img src="x" onerror="alert(1)">')
    expect(out).not.toContain('onerror')
    expect(out).not.toContain('alert(1)')
    // img tag itself may survive but without handler
    expect(out.toLowerCase()).not.toContain('onerror')
  })

  it('strips javascript: URLs', () => {
    const out = sanitizeHtml('[click](javascript:alert(1))')
    expect(out.toLowerCase()).not.toContain('javascript:')
  })

  it('preserves safe markdown output: bold, headings, lists', () => {
    const bold = sanitizeHtml('hello **bold**')
    expect(bold).toContain('<strong>bold</strong>')

    const h = sanitizeHtml('# Hello')
    expect(h).toContain('<h1')

    const list = sanitizeHtml('- a\n- b')
    expect(list).toContain('<li>')
  })

  it('preserves code blocks while stripping scripts inside', () => {
    const out = sanitizeHtml('```\ncode\n```\n<script>evil</script>')
    expect(out).not.toContain('<script>')
    // marked renders code blocks as <pre><code>
    expect(out).toContain('<code>')
  })

  it('produces safe HTML that does not contain script even for mixed payload', () => {
    const payload = '# Title\n\nHello <script>alert(1)</script> **world**'
    const out = sanitizeHtml(payload)
    expect(out).not.toContain('<script>')
    expect(out).toContain('<strong>world</strong>')
  })
})
