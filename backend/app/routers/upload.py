import contextlib
import os
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from backend.app.config import settings
from backend.app.models.schemas import TaskInfo, UploadResponse
from backend.app.routers.deps import TaskDep
from backend.app.services.pipeline import cancel_pipeline
from backend.app.services.store import create_task, get_store

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".opus", ".aac", ".wma"}


def _allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def _is_valid_magic(ext: str, header: bytes) -> bool:
    """Check whether *header* matches the expected container for *ext*.

    Empty header is treated as valid here so the downstream empty-file branch
    can emit its dedicated「空文件」message; otherwise magic mismatch returns
    the generic「文件内容与音频格式不符」error.
    """
    if len(header) == 0:
        return True
    # Per-extension allowlist
    if ext == ".wav":
        return header.startswith(b"RIFF")
    if ext == ".flac":
        return header.startswith(b"fLaC")
    if ext in (".ogg", ".oga", ".opus"):
        return header.startswith(b"OggS")
    if ext == ".mp3":
        return header.startswith(b"ID3") or (
            len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
        )
    if ext in (".m4a", ".mp4", ".mov"):
        return len(header) >= 8 and header[4:8] == b"ftyp"
    # Fallback for remaining ALLOWED_EXTENSIONS (.webm, .aac, .wma, etc.):
    # accept only if header matches any generic audio signature above.
    if header.startswith(b"RIFF"):
        return True
    if header.startswith(b"fLaC"):
        return True
    if header.startswith(b"OggS"):
        return True
    if header.startswith(b"ID3"):
        return True
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return True
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return True
    # WebM/EBML container
    if header.startswith(b"\x1aE\xdf\xa3"):
        return True
    # WMA/ASF container (Header GUID 3026B2758E66CF11)
    return header.startswith(bytes.fromhex("3026B2758E66CF11"))


@router.post("/upload", response_model=UploadResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    if not file.filename or not _allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式，支持: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    ext = os.path.splitext(file.filename)[1].lower()
    max_size = settings.max_upload_bytes

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            cl = int(content_length)
            if cl > max_size:
                raise HTTPException(
                    status_code=413,
                    detail=f"文件超过 {max_size // (1024 * 1024)}MB 限制",
                )
        except ValueError:
            pass

    header = await file.read(8)
    if not _is_valid_magic(ext, header):
        raise HTTPException(status_code=400, detail="文件内容与音频格式不符")
    await file.seek(0)

    safe_name = f"{uuid.uuid4().hex[:12]}{ext}"
    filepath = os.path.join(settings.upload_dir, safe_name)

    written = 0
    overflow = False
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
        with contextlib.suppress(OSError):
            os.remove(filepath)
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {max_size // (1024 * 1024)}MB 限制",
        )

    if written == 0:
        with contextlib.suppress(OSError):
            os.remove(filepath)
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
async def get_task_info(task: TaskDep):
    return task


@router.delete("/task/{task_id}")
async def delete_task(task_id: str, task: TaskDep):
    cancel_pipeline(task_id)
    try:
        if task.audio_path and os.path.exists(task.audio_path):
            os.remove(task.audio_path)
    except OSError:
        pass
    get_store().delete(task_id)
    return {"status": "ok"}
