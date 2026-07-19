import asyncio
import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from backend.app.services.pipeline import get_task, run_pipeline
from backend.app.models.schemas import TaskInfo

router = APIRouter(prefix="/api", tags=["transcribe"])


@router.post("/transcribe/{task_id}")
async def start_transcribe(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    asyncio.create_task(run_pipeline(task_id))
    return {"status": "started", "task_id": task_id}


@router.get("/transcribe/{task_id}/stream")
async def stream_progress(task_id: str):
    async def event_generator():
        last_overall = -1.0
        while True:
            task = get_task(task_id)
            if task is None:
                yield {"event": "error", "data": json.dumps({"error": "Task not found"})}
                break

            current_json = task.model_dump_json(exclude={"result", "minutes"})
            yield {"event": "progress", "data": current_json}

            if task.status == "done":
                full_json = task.model_dump_json()
                yield {"event": "done", "data": full_json}
                break
            elif task.status == "error":
                yield {"event": "error", "data": json.dumps({"error": task.error})}
                break

            await asyncio.sleep(1)

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
    }
