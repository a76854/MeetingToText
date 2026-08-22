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
