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
