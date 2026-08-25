import { describe, it, expect, vi, beforeEach } from 'vitest'
import { copyText, copyWithFeedback } from './clipboard'
import type { FeedbackMessenger } from './clipboard'

function messenger(): FeedbackMessenger & { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> } {
  return {
    success: vi.fn() as unknown as FeedbackMessenger['success'] & ReturnType<typeof vi.fn>,
    error: vi.fn() as unknown as FeedbackMessenger['error'] & ReturnType<typeof vi.fn>,
  }
}

describe('copyText', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('returns true when navigator.clipboard.writeText resolves', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } } as unknown as Navigator)
    await expect(copyText('hello')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith('hello')
  })

  it('returns false when writeText rejects', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    vi.stubGlobal('navigator', { clipboard: { writeText } } as unknown as Navigator)
    await expect(copyText('hello')).resolves.toBe(false)
  })

  it('returns false when clipboard is missing (throws)', async () => {
    vi.stubGlobal('navigator', {} as unknown as Navigator)
    await expect(copyText('x')).resolves.toBe(false)
  })
})

describe('copyWithFeedback', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('calls message.success with Chinese wording on success', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } } as unknown as Navigator)
    const msg = messenger()
    const ok = await copyWithFeedback('some text', msg)
    expect(ok).toBe(true)
    expect(msg.success).toHaveBeenCalledWith('已复制到剪贴板')
    expect(msg.error).not.toHaveBeenCalled()
  })

  it('calls message.error with failure wording on failure', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('fail'))
    vi.stubGlobal('navigator', { clipboard: { writeText } } as unknown as Navigator)
    const msg = messenger()
    const ok = await copyWithFeedback('some text', msg)
    expect(ok).toBe(false)
    expect(msg.error).toHaveBeenCalledWith('复制失败')
    expect(msg.success).not.toHaveBeenCalled()
  })

  it('passes through the exact text to clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } } as unknown as Navigator)
    const msg = messenger()
    await copyWithFeedback('exact-payload-123', msg)
    expect(writeText).toHaveBeenCalledWith('exact-payload-123')
  })
})
