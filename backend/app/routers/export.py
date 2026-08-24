import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.app.models.schemas import TaskStatus
from backend.app.services.exporters import (
    _EXPORTERS,
    _export_md,
    _export_srt,
    _export_txt,
    _format_timestamp_srt,
)
from backend.app.services.store import get_task

router = APIRouter(prefix="/api", tags=["export"])


@router.get("/export/{task_id}")
async def export_transcript(task_id: str, format: str = "txt"):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.done or not task.result:
        raise HTTPException(status_code=400, detail="转录未完成，无法导出")

    fmt = format.lower()
    if fmt not in _EXPORTERS:
        raise HTTPException(status_code=400, detail=f"不支持的格式: {format}")

    mime, exporter, name_tpl = _EXPORTERS[fmt]
    content = exporter(task)
    filename = name_tpl.format(stem=task.filename.rsplit(".", 1)[0])
    return StreamingResponse(
        io.StringIO(content),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
