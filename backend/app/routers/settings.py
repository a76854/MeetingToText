from typing import Any

from fastapi import APIRouter

from backend.app.config import settings, set_cpu_threads
from backend.app.models.schemas import SettingsUpdate, SettingsInfo
from backend.app.services.llm import update_llm_config
from backend.app.services.asr import unload_all_asr
from backend.app.services.asr_streaming import StreamingASR
from backend.app.services.store import get_store

router = APIRouter(prefix="/api", tags=["settings"])


_INT_FIELDS = {"llm_max_tokens", "ncpu", "asr_batch_size_s", "asr_max_single_segment_time"}
_FLOAT_FIELDS = {"llm_temperature", "asr_merge_length_s"}
_BOOL_FIELDS = {"asr_merge_vad", "asr_needs_punc"}


def _coerce(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in _INT_FIELDS:
        return int(value)
    if key in _FLOAT_FIELDS:
        return float(value)
    if key in _BOOL_FIELDS:
        if isinstance(value, bool):
            return value
        return str(value).lower() == "true"
    return str(value)


@router.get("/settings", response_model=SettingsInfo)
async def get_settings():
    s = get_store()
    return SettingsInfo(
        llm_base_url=s.get_setting("llm_base_url", settings.llm_base_url),
        llm_model=s.get_setting("llm_model", settings.llm_model),
        llm_api_key_set=bool(s.get_setting("llm_api_key", "")),
        llm_temperature=float(s.get_setting("llm_temperature", str(settings.llm_temperature))),
        llm_max_tokens=int(s.get_setting("llm_max_tokens", str(settings.llm_max_tokens))),
        asr_model_type=s.get_setting("asr_model_type", settings.asr_model_type),
        asr_model_name=s.get_setting("asr_model_name", settings.asr_model_name),
        asr_needs_punc=(s.get_setting("asr_needs_punc", str(settings.asr_needs_punc)).lower() == "true"),
        ncpu=int(s.get_setting("ncpu", str(settings.ncpu))),
        asr_batch_size_s=int(s.get_setting("asr_batch_size_s", str(settings.asr_batch_size_s))),
        asr_merge_length_s=float(s.get_setting("asr_merge_length_s", str(settings.asr_merge_length_s))),
        asr_merge_vad=(s.get_setting("asr_merge_vad", "true").lower() == "true"),
        asr_max_single_segment_time=int(s.get_setting("asr_max_single_segment_time", str(settings.asr_max_single_segment_time))),
        streaming_asr_enabled=(s.get_setting("streaming_asr_enabled", "false").lower() == "true"),
        streaming_asr_model_name=s.get_setting("streaming_asr_model_name", settings.streaming_asr_model_name),
        browser_noise_suppression=(s.get_setting("browser_noise_suppression", "true").lower() != "false"),
        audio_source=s.get_setting("audio_source", settings.audio_source),
    )


@router.post("/settings")
async def update_settings(body: SettingsUpdate):
    s = get_store()
    updates = body.model_dump(exclude_unset=True)

    llm_touched = False
    asr_touched = False
    streaming_asr_touched = False

    # Auto-set asr_needs_punc when model_type changes
    if "asr_model_type" in updates:
        model_type = str(updates["asr_model_type"])
        needs_punc = model_type == "paraformer"
        updates.setdefault("asr_needs_punc", needs_punc)

    for key, raw in updates.items():
        if raw is None:
            continue
        if isinstance(raw, str) and not raw.strip() and key != "llm_api_key":
            continue
        value = _coerce(key, raw)
        s.set_setting(key, str(value))
        setattr(settings, key, value)
        if key == "ncpu":
            set_cpu_threads(value)
        if key.startswith("llm_"):
            llm_touched = True
        elif key == "ncpu" or key.startswith("asr_"):
            asr_touched = True
        elif key.startswith("streaming_asr_"):
            streaming_asr_touched = True

    if llm_touched and settings.llm_api_key:
        update_llm_config(settings.llm_base_url, settings.llm_api_key, settings.llm_model)

    if asr_touched:
        unload_all_asr()

    if streaming_asr_touched:
        if settings.streaming_asr_enabled:
            import asyncio
            instance = StreamingASR.get_instance(settings.streaming_asr_model_name)
            asyncio.create_task(asyncio.to_thread(instance.load))
        else:
            StreamingASR.unload_all()

    return {"status": "ok"}


@router.delete("/settings/{key}")
async def delete_setting(key: str):
    if key not in {
        "llm_base_url", "llm_api_key", "llm_model", "llm_temperature", "llm_max_tokens",
        "asr_model_type", "asr_model_name", "asr_needs_punc", "ncpu",
        "asr_batch_size_s", "asr_merge_length_s", "asr_merge_vad", "asr_max_single_segment_time",
        "streaming_asr_enabled", "streaming_asr_model_name",
        "browser_noise_suppression", "audio_source",
    }:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown setting: {key}")
    get_store().delete_setting(key)
    return {"status": "ok", "key": key}
