from fastapi import APIRouter

from backend.app.config import settings
from backend.app.models.schemas import SettingsUpdate, SettingsInfo
from backend.app.services.llm import update_llm_config

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=SettingsInfo)
async def get_settings():
    return SettingsInfo(
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        llm_api_key_set=bool(settings.llm_api_key),
        asr_model_type=settings.asr_model_type,
    )


@router.post("/settings")
async def update_settings(body: SettingsUpdate):
    if body.llm_base_url:
        settings.llm_base_url = body.llm_base_url
    if body.llm_api_key:
        settings.llm_api_key = body.llm_api_key
        update_llm_config(settings.llm_base_url, body.llm_api_key, settings.llm_model)
    if body.llm_model:
        settings.llm_model = body.llm_model
        if settings.llm_base_url and settings.llm_api_key:
            update_llm_config(settings.llm_base_url, settings.llm_api_key, body.llm_model)
    if body.asr_model_type:
        settings.asr_model_type = body.asr_model_type
    return {"status": "ok"}
