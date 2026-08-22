/**
 * Reconnect-resume E2E scenario (task 27, Metis C5 — frontend side).
 *
 * Flow under test (recorder.ts task-25/26 state machine):
 *   start recording → backend killed mid-recording → "网络已断开，正在重连…"
 *   banner + local gap MediaRecorder capture → backend restarted → backoff
 *   loop adopts the suspended session ({"status":"resumed"}) → banner clears
 *   → stop → main wav task finalizes AND the outage gap uploads as a SECOND
 *   task (recording_{id}_gap.webm) → exactly two new tasks in /api/tasks.
 *
 * The backend is spawned/killed BY THIS SPEC (python main.py, port 8000);
 * the vite dev server is expected at http://localhost:5173 (see RUNME.md /
 * playwright.config.ts webServer). See RUNME.md for full run steps.
 */
import { test, expect, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import path from 'node:path'

const REPO_ROOT = path.resolve(__file, '..', '..', '..')
const BACKEND_PORT = 8000
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`
const BACKEND_CMD = process.env.MTT_BACKEND_CMD ?? 'python'
const BACKEND_ARGS = (process.env.MTT_BACKEND_ARGS ?? 'main.py').split(' ').filter(Boolean)
// Backend must stay DOWN long enough for the gap MediaRecorder (1s timeslice)
// to produce at least one chunk, so the gap blob is non-empty at stop.
const OUTAGE_MS = 3000

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

async function startBackend(): Promise<ChildProcess> {
  const proc = spawn(BACKEND_CMD, BACKEND_ARGS, {
    cwd: REPO_ROOT,
    env: process.env,
    stdio: 'ignore',
    detached: false,
  })
  const deadline = Date.now() + 180_000 // first start may preload ASR models
  while (Date.now() < deadline) {
    if (proc.exitCode !== null || proc.signalCode !== null) {
      throw new Error(`backend exited early (code=${proc.exitCode} signal=${proc.signalCode})`)
    }
    try {
      const r = await fetch(`${BACKEND_URL}/api/tasks`)
      if (r.ok) return proc
    } catch {
      /* not up yet */
    }
    await sleep(500)
  }
  proc.kill('SIGKILL')
  throw new Error('backend did not become ready within 180s')
}

async function killBackend(proc: ChildProcess): Promise<void> {
  proc.kill('SIGKILL')
  await new Promise<void>((resolve) => {
    const t = setInterval(() => {
      if (proc.exitCode !== null || proc.signalCode !== null) {
        clearInterval(t)
        resolve()
      }
    }, 50)
  })
  // give the OS a beat to close sockets so the browser sees the drop promptly
  await sleep(200)
}

async function taskCount(page: Page): Promise<number> {
  const r = await page.request.get(`${BACKEND_URL}/api/tasks`)
  expect(r.ok()).toBeTruthy()
  const body = (await r.json()) as { tasks: unknown[] }
  return body.tasks.length
}

test('reconnect-resume: banner appears, resumes after restart, stop yields main+gap tasks', async ({ page }) => {
  test.setTimeout(240_000)

  const before = await (async () => {
    let backend = await startBackend()
    try {
      return { backend, count: await taskCount(page) }
    } catch (e) {
      await killBackend(backend)
      throw e
    }
  })()
  let backend = before.backend

  try {
    const wsPromise = page.waitForEvent('websocket', { timeout: 30_000 })
    await page.goto('/record')
    await page.getByRole('button', { name: '开始录音' }).click()

    const ws = await wsPromise
    expect(ws.url()).toMatch(/\/api\/record\//)
    const taskId = ws.url().split('/').pop() as string

    // recording actually started (timer ticking past 00:00)
    await expect(page.getByText(/^00:0[1-9]$/)).toBeVisible({ timeout: 15_000 })

    // ---- interrupt: kill the backend mid-recording ----
    await killBackend(backend)

    // reconnect banner surfaces (liveError NAlert on RecordPage)
    const banner = page.getByText('网络已断开，正在重连…')
    await expect(banner).toBeVisible({ timeout: 15_000 })

    // keep the server down so the gap recorder accumulates audio
    await sleep(OUTAGE_MS)

    // ---- restore: restart the backend; backoff loop re-adopts the session ----
    backend = await startBackend()
    await expect(banner).toBeHidden({ timeout: 30_000 })

    // ---- stop: main wav finalizes + gap webm uploads as a second task ----
    const gapUpload = page
      .waitForResponse(
        (r) => r.url().includes('/api/upload') && r.request().method() === 'POST',
        { timeout: 30_000 },
      )
      .catch(() => null)
    await page.getByRole('button', { name: '停止录音' }).click()

    // done handler navigates to the finalized main task's transcript page
    await page.waitForURL(/\/transcript\//, { timeout: 30_000 })

    const gapResp = await gapUpload
    expect(gapResp, 'gap webm should be uploaded as its own task').not.toBeNull()
    const gapPost = gapResp!.request().postData() ?? ''
    expect(gapPost).toContain('_gap.webm')

    // exactly TWO new tasks appeared (main wav + gap webm)
    const after = await taskCount(page)
    expect(after).toBe(before.count + 2)
  } finally {
    await killBackend(backend).catch(() => {})
  }
})
