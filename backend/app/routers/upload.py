import os
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.app.config import settings
from backend.app.services.pipeline import create_task, run_pipeline, get_task
from backend.app.models.schemas import UploadResponse, TaskInfo, TaskStatus

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

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    task = create_task(filename=file.filename, audio_path=filepath)
    return UploadResponse(task_id=task.id, filename=file.filename)


@router.get("/task/{task_id}", response_model=TaskInfo)
async def get_task_info(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
