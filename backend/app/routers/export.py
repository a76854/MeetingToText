import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.app.models.schemas import TaskStatus
from backend.app.routers.deps import TaskDep
from backend.app.services.exporters import (
    _EXPORTERS,
)

router = APIRouter(prefix="/api", tags=["export"])


@router.get("/export/{task_id}")
async def export_transcript(task: TaskDep, format: str = "txt"):
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
