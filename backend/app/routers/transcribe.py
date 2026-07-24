import asyncio
import json
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.app.services.pipeline import get_task, submit_pipeline
from backend.app.services.store import get_store
from backend.app.models.schemas import TaskStatus, TranscriptSegment

router = APIRouter(prefix="/api", tags=["transcribe"])


class TranscriptUpdate(BaseModel):
    segments: list[TranscriptSegment]


@router.post("/transcribe/{task_id}")
async def start_transcribe(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status == TaskStatus.processing:
        raise HTTPException(status_code=400, detail="任务正在转录中")
    submit_pipeline(task_id)
    return {"status": "started", "task_id": task_id}


@router.post("/transcribe/{task_id}/retry")
async def retry_transcribe(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.audio_path or not os.path.exists(task.audio_path):
        raise HTTPException(status_code=400, detail="音频文件不存在，无法重新转录")
    if task.status == TaskStatus.processing:
        raise HTTPException(status_code=400, detail="任务正在转录中")
    get_store().reset_for_retry(task_id)
    submit_pipeline(task_id)
    return {"status": "restarted", "task_id": task_id}


@router.get("/transcribe/{task_id}/stream")
async def stream_progress(task_id: str):
    async def event_generator():
        last_status = ""
        last_progress_sig: tuple | None = None
        while True:
            task = get_task(task_id)
            if task is None:
                yield {"event": "error", "data": json.dumps({"error": "Task not found"}, ensure_ascii=False)}
                break

            current = task.status.value
            progress_sig = (
                task.progress.current_step,
                task.progress.overall,
                tuple((s.name, s.status) for s in task.progress.steps),
            )
            status_changed = current != last_status
            progress_changed = progress_sig != last_progress_sig

            if status_changed or progress_changed:
                task_json = task.model_dump_json()
                if current == TaskStatus.done.value:
                    yield {"event": "done", "data": task_json}
                    break
                elif current == TaskStatus.error.value:
                    yield {"event": "error", "data": json.dumps({"error": task.error}, ensure_ascii=False)}
                    break
                else:
                    yield {"event": "progress", "data": task_json}
                last_status = current
                last_progress_sig = progress_sig

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@router.get("/transcript/{task_id}")
async def get_transcript(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.id,
        "status": task.status.value,
        "full_text": task.result.full_text if task.result else "",
        "segments": [s.model_dump() for s in task.result.segments] if task.result else [],
        "duration": task.result.duration if task.result else 0.0,
        "error": task.error or "",
    }


@router.put("/transcript/{task_id}")
async def update_transcript(task_id: str, body: TranscriptUpdate):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.done:
        raise HTTPException(status_code=400, detail="只有已完成的任务才能编辑")

    segments = body.segments
    parts = []
    for seg in segments:
        label = f"[{seg.speaker}] " if seg.speaker else ""
        parts.append(f"{label}{seg.text}")
    full_text = "\n\n".join(parts)

    get_store().update_segments(task_id, segments, full_text)
    return {"status": "ok", "task_id": task_id, "segment_count": len(segments)}
