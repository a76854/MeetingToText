import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.app.services.pipeline import get_task

router = APIRouter(prefix="/api", tags=["audio"])


@router.get("/audio/{task_id}")
async def get_audio(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.audio_path or not os.path.exists(task.audio_path):
        raise HTTPException(status_code=404, detail="音频文件不存在")
    return FileResponse(
        task.audio_path,
        media_type="audio/wav",
        filename=os.path.basename(task.audio_path),
    )
