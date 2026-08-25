import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.app.routers.deps import TaskDep

router = APIRouter(prefix="/api", tags=["audio"])


_AUDIO_MIME = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".opus": "audio/opus",
    ".aac": "audio/aac",
    ".wma": "audio/x-ms-wma",
}


@router.get("/audio/{task_id}")
async def get_audio(task: TaskDep):
    if not task.audio_path or not os.path.exists(task.audio_path):
        raise HTTPException(status_code=404, detail="音频文件不存在")
    ext = os.path.splitext(task.audio_path)[1].lower()
    media_type = _AUDIO_MIME.get(ext, "application/octet-stream")
    return FileResponse(
        task.audio_path,
        media_type=media_type,
        filename=os.path.basename(task.audio_path),
    )
