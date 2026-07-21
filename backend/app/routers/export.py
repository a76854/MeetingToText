import io
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.app.services.pipeline import get_task
from backend.app.models.schemas import TaskStatus

router = APIRouter(prefix="/api", tags=["export"])


def _format_timestamp_srt(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _export_txt(task) -> str:
    if not task.result:
        return ""
    parts = []
    for seg in task.result.segments:
        label = f"[{seg.speaker}] " if seg.speaker else ""
        parts.append(f"{label}{seg.text}")
    return "\n".join(parts)


def _export_md(task) -> str:
    lines = [f"# 会议转录 — {task.filename}", ""]
    if task.result and task.result.duration:
        total_s = int(task.result.duration)
        h, total_s = divmod(total_s, 3600)
        m, s = divmod(total_s, 60)
        if h:
            lines.append(f"> 时长: {h}h{m}m{s}s  |  任务ID: `{task.id}`")
        else:
            lines.append(f"> 时长: {m}m{s}s  |  任务ID: `{task.id}`")
        lines.append("")
    if task.result and task.result.segments:
        for i, seg in enumerate(task.result.segments, 1):
            start_s = int(seg.start)
            start_h, start_m = divmod(start_s, 3600)
            start_m, start_s = divmod(start_m, 60)
            end_s = int(seg.end)
            end_h, end_m = divmod(end_s, 3600)
            end_m, end_s = divmod(end_m, 60)
            if start_h:
                start = f"{start_h}:{start_m:02d}:{start_s:02d}"
            else:
                start = f"{start_m}:{start_s:02d}"
            if end_h:
                end = f"{end_h}:{end_m:02d}:{end_s:02d}"
            else:
                end = f"{end_m}:{end_s:02d}"
            speaker = seg.speaker or "未知"
            lines.append(f"## {i}. [{start}–{end}] {speaker}")
            lines.append("")
            lines.append(seg.text)
            lines.append("")
    if task.minutes:
        lines.append("---")
        lines.append("")
        lines.append("# 会议纪要")
        lines.append("")
        lines.append(task.minutes)
    return "\n".join(lines)


def _export_srt(task) -> str:
    if not task.result:
        return ""
    blocks = []
    for i, seg in enumerate(task.result.segments, 1):
        blocks.append(str(i))
        blocks.append(f"{_format_timestamp_srt(seg.start)} --> {_format_timestamp_srt(seg.end)}")
        if seg.speaker:
            blocks.append(f"[{seg.speaker}] {seg.text}")
        else:
            blocks.append(seg.text)
        blocks.append("")
    return "\n".join(blocks)


_EXPORTERS = {
    "txt": ("text/plain; charset=utf-8", _export_txt, "{stem}.txt"),
    "md": ("text/markdown; charset=utf-8", _export_md, "{stem}.md"),
    "srt": ("application/x-subrip; charset=utf-8", _export_srt, "{stem}.srt"),
}


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
