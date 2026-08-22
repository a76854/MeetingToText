import os
import json
import uuid
import asyncio
import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.app.config import settings
from backend.app.services.recorder import recorder_manager
from backend.app.services.pipeline import create_task, submit_pipeline
from backend.app.services.asr_streaming import StreamingASR

router = APIRouter(prefix="/api", tags=["record"])

# Defense-in-depth vs unbounded audio_buffer growth when streaming setup stalls/fails (bug B5)
AUDIO_BUFFER_MAX_SECONDS = 10

# A connection is considered dead after this many multiples of
# reconnect_grace_seconds without ANY frame (audio chunks count; the client
# also sends {"type":"ping"} every ~10s).
LIVENESS_TIMEOUT_MULTIPLIER = 3

# Pending grace-expiry finalizers keyed by task_id (one per suspended session).
_grace_timers: dict[str, asyncio.Task] = {}


def _cancel_grace_timer(task_id: str) -> None:
    timer = _grace_timers.pop(task_id, None)
    if timer is not None and not timer.done():
        timer.cancel()


def _schedule_grace_timer(task_id: str) -> None:
    _cancel_grace_timer(task_id)
    grace = max(int(settings.reconnect_grace_seconds), 0)
    timer = asyncio.create_task(_finalize_after_grace(task_id, grace))
    _grace_timers[task_id] = timer


async def _finalize_audio_to_task(task_id: str) -> str | None:
    """Single source for 'wav -> task -> pipeline' (explicit stop AND grace expiry)."""
    audio_path = await recorder_manager.stop_recording(task_id)
    if audio_path and os.path.exists(audio_path):
        task = create_task(filename=os.path.basename(audio_path), audio_path=audio_path)
        submit_pipeline(task.id)
        return task.id
    return None


async def _finalize_after_grace(task_id: str, grace_seconds: int) -> None:
    try:
        await asyncio.sleep(grace_seconds)
    except asyncio.CancelledError:
        return
    _grace_timers.pop(task_id, None)
    # No await between this check and stop_recording's pop, so a concurrent
    # reconnect can never slip in between check and finalize.
    if recorder_manager.get_session_state(task_id) != "suspended":
        return
    logger.info(f"reconnect grace expired for task={task_id}; finalizing")
    created = await _finalize_audio_to_task(task_id)
    logger.info(f"grace-expiry finalize for task={task_id} created pipeline task={created}")


@router.websocket("/record/{task_id}")
async def record_websocket(websocket: WebSocket, task_id: str):
    await websocket.accept()

    conn_id = uuid.uuid4().hex

    state = recorder_manager.get_session_state(task_id)
    resumed = False
    if state == "suspended":
        _cancel_grace_timer(task_id)
        resumed = await recorder_manager.resume_recording(task_id, conn_id)
    elif state is None:
        _cancel_grace_timer(task_id)
        await recorder_manager.start_recording(task_id)

    if not recorder_manager.attach_owner(task_id, conn_id):
        try:
            await websocket.send_text(json.dumps({
                "status": "error",
                "code": "session_busy",
                "message": "recording session is owned by another connection",
            }, ensure_ascii=False))
        except Exception:
            pass
        await websocket.close(code=1008)
        return

    if resumed:
        try:
            await websocket.send_text(json.dumps({"status": "resumed"}, ensure_ascii=False))
        except Exception:
            pass

    liveness_timeout = LIVENESS_TIMEOUT_MULTIPLIER * max(int(settings.reconnect_grace_seconds), 0)
    if liveness_timeout <= 0:
        liveness_timeout = 0.05

    intent: str | None = None
    streaming_session = None
    final_streaming_session = None
    audio_buffer: list[bytes] = []
    sample_rate: int = 0
    model_loading: asyncio.Task | None = None
    streaming_ready = False
    cancelled = False

    async def _load_and_create_session():
        nonlocal streaming_session, streaming_ready, model_loading
        try:
            instance = StreamingASR.get_instance(settings.streaming_asr_model_name)
            await asyncio.to_thread(instance.load)
            if cancelled:
                return
            session = await asyncio.to_thread(instance.create_session, sample_rate)
            chunks_to_feed = audio_buffer[:]
            audio_buffer.clear()
            streaming_session = session
            streaming_ready = True
            for chunk in chunks_to_feed:
                if cancelled:
                    break
                partial = session.add_pcm_chunk(chunk)
                if partial:
                    try:
                        await websocket.send_text(json.dumps({
                            "type": "partial",
                            "text": partial,
                        }, ensure_ascii=False))
                    except Exception:
                        break
            logger.info(f"streaming ASR ready for task={task_id}")
        except Exception as e:
            logger.error(f"streaming ASR load-failed for task={task_id}: {e}")
            model_loading = None
            streaming_ready = False
            streaming_session = None
            audio_buffer.clear()

    async def _cancel_streaming():
        nonlocal cancelled, model_loading, streaming_session, streaming_ready
        nonlocal final_streaming_session
        cancelled = True
        if model_loading and not model_loading.done():
            model_loading.cancel()
        model_loading = None
        # Capture before nulling so the post-loop finalize on explicit stop
        # actually sees the session (was dead code before the fix).
        if streaming_session is not None:
            final_streaming_session = streaming_session
        streaming_session = None
        streaming_ready = False
        audio_buffer.clear()

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
                chunk = data["bytes"]
                await recorder_manager.add_chunk(task_id, chunk)

                if not settings.streaming_asr_enabled:
                    if model_loading is not None or streaming_session is not None:
                        await _cancel_streaming()
                elif streaming_ready and streaming_session is not None:
                    try:
                        partial = streaming_session.add_pcm_chunk(chunk)
                        if partial:
                            await websocket.send_text(json.dumps({
                                "type": "partial",
                                "text": partial,
                            }, ensure_ascii=False))
                    except Exception as e:
                        logger.warning(f"streaming ASR error: {e}")
                elif model_loading is not None:
                    audio_buffer.append(chunk)
                    max_buffer_bytes = (sample_rate or 16000) * 2 * AUDIO_BUFFER_MAX_SECONDS
                    while sum(len(c) for c in audio_buffer) > max_buffer_bytes:
                        audio_buffer.pop(0)
            elif "text" in data:
                msg = json.loads(data["text"])
                action = msg.get("action")
                if action == "stop":
                    intent = "stop"
                    break
                if action == "discard":
                    intent = "discard"
                    break
                if msg.get("type") == "config" and isinstance(msg.get("sample_rate"), int):
                    sample_rate = msg["sample_rate"]
                    await recorder_manager.set_sample_rate(task_id, sample_rate)
                    if settings.streaming_asr_enabled and sample_rate > 0 and model_loading is None:
                        model_loading = asyncio.create_task(_load_and_create_session())
                        logger.info(f"streaming ASR loading in background for task={task_id}")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await _cancel_streaming()
        recorder_manager.detach_owner(task_id, conn_id)

    if intent == "discard":
        _cancel_grace_timer(task_id)
        await recorder_manager.discard_recording(task_id)
        try:
            await websocket.send_text(json.dumps({"status": "discarded"}, ensure_ascii=False))
        except Exception:
            pass
        return

    if intent != "stop":
        # Plain disconnect / liveness death -> suspend (NOT cancel); the grace
        # timer finalizes if no client adopts the session in time.
        if await recorder_manager.suspend_recording(task_id):
            _schedule_grace_timer(task_id)
            logger.info(
                f"recording suspended for task={task_id}; "
                f"grace={settings.reconnect_grace_seconds}s"
            )
        return

    _cancel_grace_timer(task_id)

    if final_streaming_session is not None:
        try:
            final_partial = await asyncio.to_thread(final_streaming_session.finalize)
            if final_partial:
                await websocket.send_text(json.dumps({
                    "type": "partial",
                    "text": final_partial,
                    "final": True,
                }, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"streaming ASR finalize error: {e}")

    created = await _finalize_audio_to_task(task_id)
    if created:
        try:
            await websocket.send_text(json.dumps({"status": "done", "task_id": created}, ensure_ascii=False))
        except Exception:
            pass
    else:
        try:
            await websocket.send_text(json.dumps({"status": "error", "message": "No audio recorded"}, ensure_ascii=False))
        except Exception:
            pass


@router.delete("/record/{task_id}")
async def discard_record_session(task_id: str):
    """Discard a suspended (or active) recording: delete file, create no task."""
    _cancel_grace_timer(task_id)
    if not recorder_manager.has_session(task_id):
        raise HTTPException(status_code=404, detail="no recording session")
    ok = await recorder_manager.discard_recording(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="no recording session")
    return {"status": "discarded"}
