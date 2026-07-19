from fastapi import APIRouter, HTTPException

from backend.app.config import settings
from backend.app.models.schemas import GenerateRequest, GenerateResponse
from backend.app.services.pipeline import get_task
from backend.app.services.llm import get_llm
from backend.app.services.store import get_store
from backend.app.templates.presets import get_template, get_templates

router = APIRouter(prefix="/api", tags=["generate"])


@router.get("/templates")
async def list_templates():
    return {"templates": get_templates()}


@router.post("/generate", response_model=GenerateResponse)
async def generate_minutes(req: GenerateRequest):
    task = get_task(req.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.result is None or not task.result.full_text:
        raise HTTPException(status_code=400, detail="No transcript available")

    template = get_template(req.template_id)
    if template is None:
        raise HTTPException(status_code=400, detail=f"Unknown template: {req.template_id}")

    system_prompt = template["system_prompt"]
    output_format = template.get("output_format", "")
    if output_format:
        system_prompt += f"\n\n请按照以下格式输出：\n{output_format}"

    user_message = f"请根据以下会议转录内容生成会议纪要：\n\n=== 会议转录开始 ===\n{task.result.full_text}\n=== 会议转录结束 ==="

    if req.custom_instructions:
        user_message += f"\n\n额外要求：{req.custom_instructions}"

    llm = get_llm()
    minutes = llm.generate(
        system_prompt=system_prompt,
        user_message=user_message,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )

    task.minutes = minutes
    get_store().save_minutes(req.task_id, minutes)
    return GenerateResponse(minutes=minutes)
