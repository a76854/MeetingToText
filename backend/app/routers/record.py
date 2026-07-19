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

router = APIRouter(prefix="/api", tags=["record"])


@router.post("/record/start", response_model=UploadResponse)
async def start_recording():
    task_id = uuid.uuid4().hex[:12]
    filepath = await recorder_manager.start_recording(task_id)
    return UploadResponse(task_id=task_id, filename=os.path.basename(filepath))


@router.websocket("/record/{task_id}")
async def record_websocket(websocket: WebSocket, task_id: str):
    await websocket.accept()
    rec = recorder_manager._active_recordings.get(task_id)
    if rec is None:
        await websocket.close(code=1008, reason="Recording not started")
        return

    try:
        while True:
            data = await websocket.receive()
            if "bytes" in data:
                await recorder_manager.add_chunk(task_id, data["bytes"])
            elif "text" in data:
                msg = json.loads(data["text"])
                if msg.get("action") == "stop":
                    break
                if msg.get("type") == "config" and isinstance(msg.get("sample_rate"), int):
                    await recorder_manager.set_sample_rate(task_id, msg["sample_rate"])
    except WebSocketDisconnect:
        pass
    except Exception:
        pass

    audio_path = await recorder_manager.stop_recording(task_id)
    if audio_path and os.path.exists(audio_path):
        task = create_task(filename=os.path.basename(audio_path), audio_path=audio_path)
        asyncio.create_task(run_pipeline(task.id))
        await websocket.send_text(json.dumps({"status": "done", "task_id": task.id}))
    else:
        await websocket.send_text(json.dumps({"status": "error", "message": "No audio recorded"}))
