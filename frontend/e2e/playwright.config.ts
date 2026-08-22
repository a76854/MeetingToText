// Playwright config for the reconnect-resume E2E scenario (see RUNME.md).
import { defineConfig } from '@playwright/test'
import path from 'node:path'

const REPO_ROOT = path.resolve(__file, '..', '..', '..')

export default defineConfig({
  testDir: path.dirname(__file),
  timeout: 240_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.MTT_BASE_URL ?? 'http://localhost:5173',
    headless: true,
    launchOptions: {
      args: [
        '--use-fake-ui-for-media-stream', // auto-grant mic permission
        '--use-fake-device-for-media-stream', // synthetic audio instead of a real mic
      ],
    },
  },
  // The spec spawns/kills the BACKEND itself; vite is started here unless one
  // is already running on :5173.
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    cwd: path.join(REPO_ROOT, 'frontend'),
    timeout: 60_000,
  },
})
