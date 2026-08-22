/** Trigger a browser download of `url` via a temporary anchor (no object URL lifecycle). */
export function downloadUrl(url: string, filename = ''): void {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

/**
 * Save `blob` to the client as `filename`. An empty filename keeps
 * `a.download = ''`, deferring naming to the server's Content-Disposition.
 */
export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  try {
    downloadUrl(url, filename)
  } finally {
    URL.revokeObjectURL(url)
  }
}

/** Save `text` to the client as `filename` (defaults to Markdown MIME). */
export function downloadText(
  filename: string,
  text: string,
  mime = 'text/markdown;charset=utf-8',
): void {
  downloadBlob(filename, new Blob([text], { type: mime }))
}
