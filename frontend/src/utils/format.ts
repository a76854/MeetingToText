/**
 * Format an ISO datetime string as local `YYYY-MM-DD HH:mm` (falls back to the input on parse failure).
 */
export function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  } catch {
    return iso
  }
}

/**
 * Format a duration in seconds as `h:mm:ss` (1h+) or zero-padded `mm:ss`.
 * Non-numeric input (NaN/undefined/null) renders as an empty string,
 * matching the previous TranscriptPage behavior for unloaded audio metadata.
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds && seconds !== 0) return ''
  const s = Math.floor(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  }
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}
