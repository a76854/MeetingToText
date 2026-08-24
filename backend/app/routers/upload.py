import os
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.app.config import settings
from backend.app.services.pipeline import cancel_pipeline
from backend.app.services.store import create_task, get_store, get_task
from backend.app.models.schemas import UploadResponse, TaskInfo

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".opus", ".aac", ".wma"}


def _allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    if not file.filename or not _allowed_file(file.filename):
        raise HTTPException(status_code=400, detail=f"不支持的文件格式，支持: {', '.join(ALLOWED_EXTENSIONS)}")

    ext = os.path.splitext(file.filename)[1].lower()
    safe_name = f"{uuid.uuid4().hex[:12]}{ext}"
    filepath = os.path.join(settings.upload_dir, safe_name)

    written = 0
    overflow = False
    max_size = settings.max_upload_bytes
    chunk_size = 1024 * 1024
    with open(filepath, "wb") as f:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            if written + len(chunk) > max_size:
                overflow = True
                break
            f.write(chunk)
            written += len(chunk)

    if overflow:
        try:
            os.remove(filepath)
        except OSError:
            pass
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {max_size // (1024 * 1024)}MB 限制",
        )

    if written == 0:
        try:
            os.remove(filepath)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="空文件")

    task = create_task(filename=file.filename, audio_path=filepath)
    return UploadResponse(task_id=task.id, filename=file.filename)


@router.get("/tasks")
async def list_tasks(limit: int = 50):
    tasks = get_store().list_tasks(limit=limit)
    return {
        "tasks": [
            {
                "id": t.id,
                "filename": t.filename,
                "status": t.status.value,
                "created_at": t.created_at,
                "duration": t.result.duration if t.result else 0.0,
                "has_minutes": bool(t.minutes),
                "has_transcript": bool(t.result and (t.result.segments or t.result.full_text)),
                "error": t.error or "",
            }
            for t in tasks
        ]
    }


@router.get("/task/{task_id}", response_model=TaskInfo)
async def get_task_info(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/task/{task_id}")
async def delete_task(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    cancel_pipeline(task_id)
    try:
        if task.audio_path and os.path.exists(task.audio_path):
            os.remove(task.audio_path)
    except OSError:
        pass
    get_store().delete(task_id)
    return {"status": "ok", "task_id": task_id}
