import os
import uuid
import json
import asyncio
import shutil

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from backend.app.config import settings
from backend.app.models.schemas import UploadResponse
from backend.app.services.recorder import recorder_manager
from backend.app.services.pipeline import create_task, get_task, run_pipeline
from backend.app.services.asr_streaming import StreamingASR

router = APIRouter(prefix="/api", tags=["record"])


@router.post("/record/start", response_model=UploadResponse)
async def start_recording():
    task_id = uuid.uuid4().hex[:12]
    filepath = await recorder_manager.start_recording(task_id)
    return UploadResponse(task_id=task_id, filename=os.path.basename(filepath))


@router.websocket("/record/{task_id}")
async def record_websocket(websocket: WebSocket, task_id: str):
    await websocket.accept()

    if not recorder_manager.has_session(task_id):
        await recorder_manager.start_recording(task_id)

    intent: str | None = None
    streaming_session = None
    streaming_enabled = settings.streaming_asr_enabled

    try:
        while True:
            data = await websocket.receive()
            if "bytes" in data:
                await recorder_manager.add_chunk(task_id, data["bytes"])
                if streaming_session is not None:
                    try:
                        partial = streaming_session.add_pcm_chunk(data["bytes"])
                        if partial:
                            await websocket.send_text(json.dumps({
                                "type": "partial",
                                "text": partial,
                            }, ensure_ascii=False))
                    except Exception as e:
                        print(f"[record] streaming ASR error: {e}")
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
                    if streaming_enabled and sample_rate > 0:
                        try:
                            streaming_model = StreamingASR.get_instance(settings.streaming_asr_model_name)
                            streaming_session = streaming_model.create_session(sample_rate)
                            print(f"[record] streaming ASR session created for task={task_id} sr={sample_rate}")
                        except Exception as e:
                            print(f"[record] failed to create streaming ASR session: {e}")
                            streaming_session = None
    except WebSocketDisconnect:
        pass
    except Exception:
        pass

    if intent == "discard":
        await recorder_manager.cancel_recording(task_id)
        try:
            await websocket.send_text(json.dumps({"status": "discarded"}, ensure_ascii=False))
        except Exception:
            pass
        return

    if intent != "stop":
        await recorder_manager.cancel_recording(task_id)
        return

    if streaming_session is not None:
        try:
            final_partial = streaming_session.finalize()
            if final_partial:
                await websocket.send_text(json.dumps({
                    "type": "partial",
                    "text": final_partial,
                    "final": True,
                }, ensure_ascii=False))
        except Exception as e:
            print(f"[record] streaming ASR finalize error: {e}")

    audio_path = await recorder_manager.stop_recording(task_id)
    if audio_path and os.path.exists(audio_path):
        task = create_task(filename=os.path.basename(audio_path), audio_path=audio_path)
        asyncio.create_task(run_pipeline(task.id))
        try:
            await websocket.send_text(json.dumps({"status": "done", "task_id": task.id}, ensure_ascii=False))
        except Exception:
            pass
    else:
        try:
            await websocket.send_text(json.dumps({"status": "error", "message": "No audio recorded"}, ensure_ascii=False))
        except Exception:
            pass
