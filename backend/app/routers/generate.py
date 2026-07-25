import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request

from backend.app.config import settings
from backend.app.models.schemas import GenerateRequest, GenerateResponse
from backend.app.services.pipeline import get_task
from backend.app.services.llm import get_llm
from backend.app.services.store import get_store
from backend.app.templates.presets import get_template, get_templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["generate"])


# Per-task hard rate limit: at most N LLM calls per WINDOW seconds.
# This is a defensive backstop against runaway clients / bots.
_RATE_LIMIT_WINDOW_S = 600
_RATE_LIMIT_MAX_CALLS = 5


def _cache_key(template_id: str, custom_instructions: str) -> str:
    raw = f"{template_id}\x00{custom_instructions.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.get("/templates")
async def list_templates():
    return {"templates": get_templates()}


@router.post("/generate", response_model=GenerateResponse)
async def generate_minutes(
    req: GenerateRequest,
    request: Request,
    x_user_triggered: str | None = Header(default=None, alias="X-User-Triggered"),
):
    client_ip = request.client.host if request.client else "unknown"
    is_user_triggered = (x_user_triggered or "").strip().lower() == "true"

    logger.info(
        "POST /api/generate task=%s template=%s force=%s ip=%s user_triggered=%s "
        "auto_generate_setting=%s",
        req.task_id, req.template_id, req.force, client_ip,
        is_user_triggered, settings.auto_generate_minutes,
    )

    # Hard rule 1: the global auto-generate switch is OFF by default.
    # When OFF, EVERY /api/generate call must come from an explicit user action
    # (frontend sets X-User-Triggered: true on real button clicks).
    if not settings.auto_generate_minutes and not is_user_triggered:
        logger.warning(
            "Rejected /api/generate (no user trigger) task=%s ip=%s. "
            "Auto-generate is disabled; calls require X-User-Triggered header.",
            req.task_id, client_ip,
        )
        raise HTTPException(
            status_code=403,
            detail="AI 总结仅在用户主动操作时调用，未检测到用户触发标识 (X-User-Triggered)。",
        )

    task = get_task(req.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.result is None or not task.result.full_text:
        raise HTTPException(status_code=400, detail="No transcript available")

    store = get_store()

    # Hard rule 2: per-task rate limit. Even legitimate users can hit the
    # button too many times; we cap it.
    stats = store.get_generate_stats(req.task_id)
    now = time.time()
    if stats["last_at"]:
        try:
            last_ts = datetime.fromisoformat(stats["last_at"]).timestamp()
        except ValueError:
            last_ts = 0.0
        if now - last_ts < _RATE_LIMIT_WINDOW_S and stats["count"] >= _RATE_LIMIT_MAX_CALLS:
            retry_after = int(_RATE_LIMIT_WINDOW_S - (now - last_ts))
            logger.warning(
                "Rate limit hit for task=%s ip=%s count=%d retry_after=%ds",
                req.task_id, client_ip, stats["count"], retry_after,
            )
            raise HTTPException(
                status_code=429,
                detail=f"该任务生成调用过于频繁，请等待 {retry_after} 秒后再试（已用 {stats['count']}/{_RATE_LIMIT_MAX_CALLS} 次）。",
                headers={"Retry-After": str(retry_after)},
            )

    row = store.get_row(req.task_id)
    cached_key = (row or {}).get("minutes_cache_key", "") or ""
    requested_key = _cache_key(req.template_id, req.custom_instructions)

    if not req.force and task.minutes and cached_key == requested_key:
        logger.info(
            "Cache hit for task=%s template=%s (saved LLM call) ip=%s",
            req.task_id, req.template_id, client_ip,
        )
        return GenerateResponse(minutes=task.minutes)

    if req.force and task.minutes:
        logger.info("Force regenerate task=%s template=%s ip=%s", req.task_id, req.template_id, client_ip)

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
    if not llm.api_key:
        raise HTTPException(status_code=400, detail="请先在设置中配置 LLM API Key")

    # Stamp the call BEFORE invoking the LLM so the rate-limit counter is
    # accurate even if the upstream call fails or times out.
    when_iso = datetime.now(timezone.utc).isoformat()
    new_count = store.record_generate_call(req.task_id, when_iso)
    logger.info("Generate call #%d for task=%s (LLM invoke starting)", new_count, req.task_id)

    try:
        minutes = await asyncio.to_thread(
            llm.generate,
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            max_input_tokens=settings.llm_max_input_tokens,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {e}")

    task.minutes = minutes
    store.save_minutes(req.task_id, minutes, requested_key)
    return GenerateResponse(minutes=minutes)
