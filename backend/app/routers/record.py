"""Record websocket handler and the DELETE discard endpoint.

The websocket handler is a thin frame pump: receive -> dispatch bytes/text ->
break on stop/discard intent. All per-connection state lives in
``WsRecordingSession`` (todo 13; previously eight closure variables mutated
via ``nonlocal``), every outgoing frame goes through ``_safe_send`` so a dying
socket can never raise inside the loop, and malformed client JSON gets an
explicit error frame instead of silently suspending the session (the pre-13
behavior: json.loads failures fell into the outer catch-all).
"""

import json
import uuid
import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.app.config import settings
from backend.app.services.recorder import recorder_manager
from backend.app.services.asr_streaming import StreamingASR
from backend.app.services.record_session import record_session_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["record"])

# Defense-in-depth vs unbounded audio_buffer growth when streaming setup stalls/fails (bug B5)
AUDIO_BUFFER_MAX_SECONDS = 10

# A connection is considered dead after this many multiples of
# reconnect_grace_seconds without ANY frame (audio chunks count; the client
# also sends {"type":"ping"} every ~10s).
LIVENESS_TIMEOUT_MULTIPLIER = 3


async def _safe_send(websocket: WebSocket, payload: dict) -> bool:
    """json.dumps + send_text; logs a warning (never raises) on send failure.

    Returns True when the frame was delivered. The buffer-replay loop uses the
    result to stop replaying into a dead socket; other call sites ignore it
    because a dead socket ends the loop anyway.
    """
    try:
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))
        return True
    except Exception as e:
        frame_kind = payload.get("status") or payload.get("type") or "unknown"
        logger.warning(f"failed to send {frame_kind} frame to ws client: {e}")
        return False


class WsRecordingSession:
    """All per-connection state for one /api/record websocket session.

    Previously eight closure variables inside record_websocket mutated via
    ``nonlocal`` (intent, streaming_session, final_streaming_session,
    audio_buffer, sample_rate, model_loading, streaming_ready, cancelled).
    Grouping them here turns the handler into a readable frame pump and gives
    the streaming-ASR half of the protocol a unit-testable home.
    """

    def __init__(self, websocket: WebSocket, task_id: str) -> None:
        self.websocket = websocket
        self.task_id = task_id
        # Loop outcome: "stop" | "discard" | None (None => suspend on death).
        self.intent: str | None = None
        self.streaming_session = None  # live streaming ASR session
        self.final_streaming_session = None  # captured on cancel, finalized on stop
        self.audio_buffer: list[bytes] = []  # chunks buffered while the model loads
        self.sample_rate: int = 0
        self.model_loading: asyncio.Task | None = None
        self.streaming_ready = False
        self.cancelled = False

    def start_streaming_loader(self) -> None:
        """Spawn the background load task (config frame with a positive rate)."""
        self.model_loading = asyncio.create_task(self._load_and_create_session())
        logger.info(f"streaming ASR loading in background for task={self.task_id}")

    async def _load_and_create_session(self) -> None:
        """Load the model, create the session, then replay buffered chunks.

        Chunks arriving while the model loads are buffered (capped); on
        completion they replay into the fresh session so no audio is lost.
        Any failure logs "load-failed" and resets the state so a later config
        frame can retry.
        """
        try:
            instance = StreamingASR.get_instance(settings.streaming_asr_model_name)
            await asyncio.to_thread(instance.load)
            if self.cancelled:
                return
            session = await asyncio.to_thread(instance.create_session, self.sample_rate)
            chunks_to_feed = self.audio_buffer[:]
            self.audio_buffer.clear()
            self.streaming_session = session
            self.streaming_ready = True
            for chunk in chunks_to_feed:
                if self.cancelled:
                    break
                partial = session.add_pcm_chunk(chunk)
                if partial:
                    # Keep the original break-on-failed-send: a dead socket
                    # stops the replay early (now logged instead of silent).
                    if not await _safe_send(self.websocket, {"type": "partial", "text": partial}):
                        break
            logger.info(f"streaming ASR ready for task={self.task_id}")
        except Exception as e:
            logger.error(f"streaming ASR load-failed for task={self.task_id}: {e}")
            self.model_loading = None
            self.streaming_ready = False
            self.streaming_session = None
            self.audio_buffer.clear()

    def cancel_streaming(self) -> None:
        """Tear down in-flight streaming work; capture the session for finalize."""
        self.cancelled = True
        if self.model_loading and not self.model_loading.done():
            self.model_loading.cancel()
        self.model_loading = None
        # Capture before nulling so the post-loop finalize on explicit stop
        # actually sees the session (was dead code before the fix).
        if self.streaming_session is not None:
            self.final_streaming_session = self.streaming_session
        self.streaming_session = None
        self.streaming_ready = False
        self.audio_buffer.clear()

    async def handle_audio_chunk(self, chunk: bytes) -> None:
        """Feed one binary frame: always append to the wav; feed ASR if ready."""
        await recorder_manager.add_chunk(self.task_id, chunk)

        if not settings.streaming_asr_enabled:
            if self.model_loading is not None or self.streaming_session is not None:
                self.cancel_streaming()
        elif self.streaming_ready and self.streaming_session is not None:
            try:
                partial = self.streaming_session.add_pcm_chunk(chunk)
                if partial:
                    await _safe_send(self.websocket, {"type": "partial", "text": partial})
            except Exception as e:
                logger.warning(f"streaming ASR error: {e}")
        elif self.model_loading is not None:
            self.audio_buffer.append(chunk)
            max_buffer_bytes = (self.sample_rate or 16000) * 2 * AUDIO_BUFFER_MAX_SECONDS
            while sum(len(c) for c in self.audio_buffer) > max_buffer_bytes:
                self.audio_buffer.pop(0)

    async def handle_control_message(self, msg: dict) -> bool:
        """Dispatch one JSON control frame; True when the loop must exit."""
        action = msg.get("action")
        if action == "stop":
            self.intent = "stop"
            return True
        if action == "discard":
            self.intent = "discard"
            return True
        if msg.get("type") == "config" and isinstance(msg.get("sample_rate"), int):
            self.sample_rate = msg["sample_rate"]
            await recorder_manager.set_sample_rate(self.task_id, self.sample_rate)
            if (
                settings.streaming_asr_enabled
                and self.sample_rate > 0
                and self.model_loading is None
            ):
                self.start_streaming_loader()
        return False

    async def finalize_streaming(self) -> None:
        """On explicit stop: flush the captured session, emit the final partial."""
        if self.final_streaming_session is None:
            return
        try:
            final_partial = await asyncio.to_thread(self.final_streaming_session.finalize)
            if final_partial:
                await _safe_send(self.websocket, {
                    "type": "partial",
                    "text": final_partial,
                    "final": True,
                })
        except Exception as e:
            logger.warning(f"streaming ASR finalize error: {e}")


async def _begin_session(websocket: WebSocket, task_id: str) -> tuple[str, bool] | None:
    """Websocket handshake + ownership adoption.

    Accepts the socket, resumes/creates the recording, binds the connection
    as owner and sends the initial frames (session_busy or resumed). Returns
    (conn_id, resumed), or None when another connection owns the session
    (caller must return immediately).
    """
    await websocket.accept()

    conn_id = uuid.uuid4().hex

    state = recorder_manager.get_session_state(task_id)
    resumed = False
    if state == "suspended":
        record_session_service.cancel_grace_timer(task_id)
        resumed = await recorder_manager.resume_recording(task_id, conn_id)
    elif state is None:
        record_session_service.cancel_grace_timer(task_id)
        await recorder_manager.start_recording(task_id)

    if not recorder_manager.attach_owner(task_id, conn_id):
        await _safe_send(websocket, {
            "status": "error",
            "code": "session_busy",
            "message": "recording session is owned by another connection",
        })
        await websocket.close(code=1008)
        return None

    if resumed:
        await _safe_send(websocket, {"status": "resumed"})

    return conn_id, resumed


@router.websocket("/record/{task_id}")
async def record_websocket(websocket: WebSocket, task_id: str):
    begun = await _begin_session(websocket, task_id)
    if begun is None:
        return
    conn_id, _ = begun

    liveness_timeout = LIVENESS_TIMEOUT_MULTIPLIER * max(int(settings.reconnect_grace_seconds), 0)
    if liveness_timeout <= 0:
        liveness_timeout = 0.05

    session = WsRecordingSession(websocket, task_id)

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive(), timeout=liveness_timeout)
            except asyncio.TimeoutError:
                logger.info(
                    f"liveness timeout ({liveness_timeout}s without frames) "
                    f"for task={task_id}; suspending"
                )
                break
            if "bytes" in data:
                await session.handle_audio_chunk(data["bytes"])
            elif "text" in data:
                try:
                    msg = json.loads(data["text"])
                except json.JSONDecodeError:
                    await _safe_send(websocket, {"status": "error", "message": "invalid json"})
                    continue
                if await session.handle_control_message(msg):
                    break
    except WebSocketDisconnect:
        # Normal drop: fall through to the post-loop suspend/finalize logic.
        pass
    except Exception:
        logger.exception(f"unexpected error in record websocket for task={task_id}")
    finally:
        session.cancel_streaming()
        recorder_manager.detach_owner(task_id, conn_id)

    if session.intent == "discard":
        record_session_service.cancel_grace_timer(task_id)
        await recorder_manager.discard_recording(task_id)
        await _safe_send(websocket, {"status": "discarded"})
        return

    if session.intent != "stop":
        # Plain disconnect / liveness death -> suspend (NOT cancel); the grace
        # timer finalizes if no client adopts the session in time.
        if await recorder_manager.suspend_recording(task_id):
            record_session_service.schedule_grace_timer(task_id)
            logger.info(
                f"recording suspended for task={task_id}; "
                f"grace={settings.reconnect_grace_seconds}s"
            )
        return

    record_session_service.cancel_grace_timer(task_id)

    await session.finalize_streaming()

    created = await record_session_service.finalize_audio_to_task(task_id)
    if created:
        await _safe_send(websocket, {"status": "done", "task_id": created})
    else:
        await _safe_send(websocket, {"status": "error", "message": "No audio recorded"})


@router.delete("/record/{task_id}")
async def discard_record_session(task_id: str):
    """Discard a suspended (or active) recording: delete file, create no task."""
    record_session_service.cancel_grace_timer(task_id)
    if not recorder_manager.has_session(task_id):
        raise HTTPException(status_code=404, detail="no recording session")
    ok = await recorder_manager.discard_recording(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="no recording session")
    return {"status": "ok"}
