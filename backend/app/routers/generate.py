import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.config import settings
from backend.app.models.schemas import GenerateRequest, GenerateResponse
from backend.app.routers.deps import TaskDep, get_task_or_404
from backend.app.services.llm import get_llm, map_llm_error
from backend.app.services.store import get_store
from backend.app.templates.presets import get_template, get_templates
from backend.app.templates.prompts import build_minutes_messages

logger = logging.getLogger(__name__)


class UpdateMinutesRequest(BaseModel):
    minutes: str

router = APIRouter(prefix="/api", tags=["generate"])


@router.get("/templates")
async def list_templates():
    return {"templates": get_templates()}


@router.post("/generate", response_model=GenerateResponse)
async def generate_minutes(req: GenerateRequest):
    task = get_task_or_404(req.task_id)
    if task.result is None or not task.result.full_text:
        raise HTTPException(status_code=400, detail="No transcript available")

    template = get_template(req.template_id)
    if template is None:
        raise HTTPException(status_code=400, detail=f"Unknown template: {req.template_id}")

    messages = build_minutes_messages(
        template_prompt=template["system_prompt"],
        transcript_text=task.result.full_text,
        custom_instructions=req.custom_instructions,
        output_format_hint=template.get("output_format", ""),
    )

    llm = get_llm()
    if not llm.api_key:
        raise HTTPException(status_code=400, detail="请先在设置中配置 LLM API Key")

    try:
        minutes = await asyncio.to_thread(
            llm.generate,
            system_prompt=messages[0]["content"],
            user_message=messages[1]["content"],
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    except Exception as e:
        logger.exception("LLM generate failed")
        raise HTTPException(status_code=500, detail=map_llm_error(e)) from e

    get_store().save_minutes(req.task_id, minutes)
    return GenerateResponse(minutes=minutes)


@router.put("/minutes/{task_id}", response_model=GenerateResponse)
async def update_minutes(task_id: str, body: UpdateMinutesRequest, task: TaskDep):
    get_store().save_minutes(task_id, body.minutes)
    return GenerateResponse(minutes=body.minutes)
