"""Recording-session orchestration: the suspend/resume/grace lifecycle.

A recording session itself lives in RecorderManager
(backend/app/services/recorder.py:116-163) as a clean two-state FSM:

    active     - a websocket owns the session and streams audio into a wav file
    suspended  - the connection dropped or died of liveness; the wav file is
                 kept so a reconnecting client can keep appending to it

This service owns everything that happens AROUND that FSM without being the
FSM itself. Three jobs:

1. schedule_grace_timer() / cancel_grace_timer() maintain the registry of
   pending grace-expiry finalizers (one per suspended session, keyed by
   task_id). When a session suspends, the router arms a timer; when a client
   reconnects and resumes before the grace elapses, the router cancels it.
2. finalize_after_grace() is the timer body: when the grace elapses and the
   session is STILL suspended (nobody adopted it), the recording is promoted
   into a pipeline task instead of being lost to a closed browser tab.
3. finalize_audio_to_task() is the single source for "wav -> task ->
   pipeline", shared by the explicit-stop path (router) and the
   grace-expiry path (this service) so both finalize identically.

Why a service and not router logic: the registry and finalize steps are a
self-contained policy with zero HTTP/WS knowledge. Keeping them inside
routers/record.py would force todo-13's websocket decomposition to drag
unrelated state along and hide a reusable lifecycle under endpoint code.
The router remains a thin adapter: translate frames to service calls.

## Lifecycle

    active --(disconnect / liveness death)--> suspended
      ^                                        |
      |                                        |  (grace timer armed)
      +----(reconnect: resume, cancel timer)---+
      |
      +----(explicit stop OR grace expiry)---> finalized -> pipeline task
      |
      +----(discard)--------------------------> deleted, no task created

## Wire protocol contract

Every frame exchanged over ``/api/record/{task_id}`` is listed below.  All
server→client frames are emitted through ``_safe_send`` (record.py:37) which
never raises; all client→server JSON frames are dispatched by
``WsRecordingSession.handle_control_message`` (record.py:150) or the binary
branch (record.py:245).

### Client → Server

- **binary WebSocket bytes** (int16 mono PCM audio chunk)
  → produced by recorder.ts AudioWorklet callback (:132 ``ws.send(i16.buffer)``)
  → consumed by record.py ``handle_audio_chunk`` (:130-148)

- **{"type":"config","sample_rate":\<int\>}**
  → produced by recorder.ts on WS open (:643) and after reconnect (:293)
  → consumed by record.py ``handle_control_message`` (:159-167); sets wav
    sample rate; a positive rate triggers the streaming ASR loader when
    ``settings.streaming_asr_enabled`` is true

- **{"action":"stop"}**
  → produced by recorder.ts ``stopRecording`` (:736), ``beforeunload`` (:653),
    and ``adoptSocket`` mid-outage (:306)
  → consumed by record.py ``handle_control_message`` (:153-155); sets intent
    to "stop", the main loop exits, and the finalize-to-pipeline path runs

- **{"action":"discard"}**
  → produced by recorder.ts ``cancelRecording`` (:755) and getUserMedia error
    path (:594)
  → consumed by record.py ``handle_control_message`` (:156-158); sets intent
    to "discard", the loop exits, and the delete-no-task path runs

- **{"type":"ping"}**
  → produced by recorder.ts heartbeat every 10s (:186)
  → consumed implicitly: any received frame resets the liveness timeout
    (record.py:238-244); the message falls through ``handle_control_message``
    with no action but counts as a liveness frame

### Server → Client

- **{"status":"resumed"}**
  → emitted by record.py ``_begin_session`` (:217) when a reconnecting client
    adopts a suspended session
  → consumed by recorder.ts ``attachWsHandlers`` (:442-445); clears error,
    sets liveStatus to 'active' when streaming ASR is enabled

- **{"type":"partial","text":"..."}**
  → emitted by record.py ``_load_and_create_session`` (:106) during buffered
    replay and ``handle_audio_chunk`` (:141) during live streaming
  → consumed by recorder.ts ``attachWsHandlers`` (:434-441); sets
    liveStatus to 'active', appends trimmed text to liveText

- **{"type":"partial","text":"...","final":true}**
  → emitted by record.py ``finalize_streaming`` (:177-181) on explicit stop
  → consumed by recorder.ts ``attachWsHandlers`` (:439-440); sets
    liveStatus to 'idle'

- **{"status":"done","task_id":"\<id\>"}**
  → emitted by record.py ``record_websocket`` (:287) after wav finalize
  → consumed by recorder.ts ``attachWsHandlers`` (:446-463); resets state,
    uploads gap audio as second task if present, navigates to transcript page

- **{"status":"error","code":"session_busy","message":"..."}**
  → emitted by record.py ``_begin_session`` (:208-212) when another connection
    owns the session
  → consumed by recorder.ts ``attachWsHandlers`` (:464-474); during
    reconnecting the stale socket is silently closed; otherwise shows error

- **{"status":"error","message":"..."}**
  → emitted by record.py for malformed JSON (:251, "invalid json") and empty
    audio (:289, "No audio recorded")
  → consumed by recorder.ts ``attachWsHandlers`` (:475-484); resets state,
    salvages gap audio if available, otherwise shows error message

- **{"status":"discarded"}**
  → emitted by record.py ``record_websocket`` (:267) on the WS cancel path
  → consumed by recorder.ts ``attachWsHandlers`` (:486); acknowledged with
    no client action (the REST DELETE at :763 is the frontend's primary cancel)

### REST (non-WS)

- **DELETE /api/record/{task_id}** returns **{"status":"ok"}**
  → record.py ``discard_record_session`` (:292-301); cancels grace timer,
    deletes file, creates no task.  Frontend calls this from
    recorder.ts ``cancelRecording`` (:763) as a safety net.
"""

import os
import asyncio
import logging

from backend.app.config import settings
from backend.app.services.recorder import recorder_manager
from backend.app.services.pipeline import submit_pipeline
from backend.app.services.store import create_task

logger = logging.getLogger(__name__)


class RecordingSessionService:
    """Owns the grace-timer registry and the finalize orchestration.

    One module-level instance (``record_session_service``) is shared by the
    router; the registry is instance state so tests can snapshot/clear it.
    """

    def __init__(self) -> None:
        # Pending grace-expiry finalizers keyed by task_id (one per suspended session).
        self._grace_timers: dict[str, asyncio.Task] = {}

    def cancel_grace_timer(self, task_id: str) -> None:
        timer = self._grace_timers.pop(task_id, None)
        if timer is not None and not timer.done():
            timer.cancel()

    def schedule_grace_timer(self, task_id: str) -> None:
        self.cancel_grace_timer(task_id)
        grace = max(int(settings.reconnect_grace_seconds), 0)
        timer = asyncio.create_task(self.finalize_after_grace(task_id, grace))
        self._grace_timers[task_id] = timer

    async def finalize_audio_to_task(self, task_id: str) -> str | None:
        """Single source for 'wav -> task -> pipeline' (explicit stop AND grace expiry)."""
        audio_path = await recorder_manager.stop_recording(task_id)
        if audio_path and os.path.exists(audio_path):
            task = create_task(filename=os.path.basename(audio_path), audio_path=audio_path)
            submit_pipeline(task.id)
            return task.id
        return None

    async def finalize_after_grace(self, task_id: str, grace_seconds: int) -> None:
        try:
            await asyncio.sleep(grace_seconds)
        except asyncio.CancelledError:
            return
        self._grace_timers.pop(task_id, None)
        # No await between this check and stop_recording's pop, so a concurrent
        # reconnect can never slip in between check and finalize.
        if recorder_manager.get_session_state(task_id) != "suspended":
            return
        logger.info(f"reconnect grace expired for task={task_id}; finalizing")
        created = await self.finalize_audio_to_task(task_id)
        logger.info(f"grace-expiry finalize for task={task_id} created pipeline task={created}")


record_session_service = RecordingSessionService()
