/**
 * Minimal structural view of a message provider (e.g. the component's
 * `useMessage()` result), kept structural so this util never imports any
 * UI framework.
 */
export interface FeedbackMessenger {
  success: (content: string) => void
  error: (content: string) => void
}

/**
 * Write `text` to the clipboard. Catches rejection internally and resolves
 * `false` on failure, so callers never produce an unhandled rejection.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

/**
 * Copy `text` and surface the outcome through the caller's message provider
 * (single shared success/failure wording for all copy buttons).
 */
export async function copyWithFeedback(text: string, message: FeedbackMessenger): Promise<boolean> {
  const ok = await copyText(text)
  if (ok) {
    message.success('已复制到剪贴板')
  } else {
    message.error('复制失败')
  }
  return ok
}
