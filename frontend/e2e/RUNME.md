# Reconnect-resume E2E (task 27)

Playwright scenario: `reconnect.spec.ts` — start recording → kill backend
mid-recording → assert the `网络已断开，正在重连…` banner → restart backend →
assert resume (banner clears) → stop → assert the main wav task AND the outage
gap webm (`recording_{id}_gap.webm`) both appear as new tasks in `/api/tasks`.

## What the spec manages itself

- **Backend**: the spec spawns `python main.py` at the repo root, waits for
  `GET /api/tasks` to answer, SIGKILLs it mid-recording, restarts it, and kills
  it again at the end. Override with `MTT_BACKEND_CMD` / `MTT_BACKEND_ARGS`
  (e.g. `MTT_BACKEND_CMD=python3.12`). First start may take a while if FunASR
  models are not cached yet (startup preloads them; failure is non-fatal).
- **Vite dev server**: auto-started by `playwright.config.ts` webServer unless
  something already answers on :5173 (`reuseExistingServer: true`).
- **Microphone**: none needed — chromium launches with
  `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream`.

## Run steps

```bash
# one-time: install the runner + browser (browsers may already be in ~/.cache/ms-playwright)
cd frontend
npm install -D @playwright/test        # add --no-save to avoid touching package.json
npx playwright install chromium        # skip if chromium is already installed

# run (from frontend/)
npx playwright test --config=e2e/playwright.config.ts e2e/reconnect.spec.ts

# headed / debug
npx playwright test --config=e2e/playwright.config.ts e2e/reconnect.spec.ts --headed
```

Manual alternative (no spec-managed backend): start `python main.py` yourself,
export nothing extra — the spec still spawns its own instance, so for a fully
manual run use `MTT_BACKEND_CMD=true MTT_BACKEND_ARGS=` … not recommended;
just let the spec own the backend.

## Assertions made (in order)

1. A websocket to `/api/record/{taskId}` opens after clicking 开始录音.
2. The timer ticks past `00:00` (recording state reached).
3. After the backend is killed, the banner text `网络已断开，正在重连…`
   becomes visible within 15s.
4. Server stays down ≥3s so the gap MediaRecorder (1s timeslice) captures audio.
5. After the backend answers again, the banner clears within 30s (backoff loop
   adopted the suspended session — server sent `{"status":"resumed"}`).
6. Clicking 停止录音 navigates to `/transcript/{mainTaskId}`.
7. A `POST /api/upload` fired whose multipart body filename ends `_gap.webm`.
8. `GET /api/tasks` count increased by exactly **2** (main + gap).

## Known constraints

- Streaming ASR must stay OFF (default) — no live partials are asserted here.
- If the machine is slow, raise `OUTAGE_MS`/timeouts rather than retry counts.
- The vite proxy forwards `/api` (incl. WS) to :8000 — keep that config intact.
