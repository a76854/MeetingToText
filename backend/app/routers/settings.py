import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.config import SETTING_SPECS, settings, settings_lock, set_cpu_threads
from backend.app.models.schemas import SettingsUpdate, SettingsInfo
from backend.app.services.llm import update_llm_config
from backend.app.services.asr import unload_all_asr
from backend.app.services.asr_streaming import StreamingASR
from backend.app.services.store import get_store

router = APIRouter(prefix="/api", tags=["settings"])

# Keep references to fire-and-forget tasks so the event loop doesn't GC them mid-run.
_bg_tasks: set[asyncio.Task] = set()


def _coerce(key: str, value: Any) -> Any:
    if value is None:
        return None
    spec = SETTING_SPECS.get(key)
    if spec is None:
        # Unreachable for SettingsUpdate fields (superset test pins this), kept
        # to preserve the former fall-through behavior for any future key.
        return str(value)
    return spec.caster(value)


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
        # C2: bool defaults derive from the runtime settings object so
        # MTT_* env overrides are visible in the UI, and every stored value
        # parses with the same .lower() == "true" rule.
        asr_merge_vad=(s.get_setting("asr_merge_vad", str(settings.asr_merge_vad)).lower() == "true"),
        asr_max_single_segment_time=int(s.get_setting("asr_max_single_segment_time", str(settings.asr_max_single_segment_time))),
        streaming_asr_enabled=(s.get_setting("streaming_asr_enabled", str(settings.streaming_asr_enabled)).lower() == "true"),
        streaming_asr_model_name=s.get_setting("streaming_asr_model_name", settings.streaming_asr_model_name),
        browser_noise_suppression=(s.get_setting("browser_noise_suppression", str(settings.browser_noise_suppression)).lower() == "true"),
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
        # Empty string means "leave unchanged" for ANY key (the settings UI sends
        # untouched fields as ""); explicit clears go through DELETE /settings/{key}.
        if isinstance(raw, str) and not raw.strip():
            continue
        with settings_lock:
            value = _coerce(key, raw)
            # Bools are stored uniformly as lowercase "true"/"false" — never
            # str(True)="True" — so every reader can use raw.lower() == "true".
            stored = str(value).lower() if isinstance(value, bool) else str(value)
            s.set_setting(key, stored)
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
            instance = StreamingASR.get_instance(settings.streaming_asr_model_name)
            task = asyncio.create_task(asyncio.to_thread(instance.load))
            _bg_tasks.add(task)
            task.add_done_callback(_bg_tasks.discard)
        else:
            StreamingASR.unload_all()

    return {"status": "ok"}


@router.delete("/settings/{key}")
async def delete_setting(key: str):
    spec = SETTING_SPECS.get(key)
    if spec is None or not spec.deletable:
        raise HTTPException(status_code=400, detail=f"Unknown setting: {key}")
    # Reset the runtime object too, otherwise generation keeps using the deleted
    # value while GET /settings reports the setting as gone. Spec defaults are
    # snapshotted from a fresh Settings() so env-provided (MTT_*) boot values
    # are preserved.
    value = spec.default
    with settings_lock:
        get_store().delete_setting(key)
        setattr(settings, key, value)
        if key == "ncpu":
            set_cpu_threads(value)
    if key.startswith("llm_"):
        # Rebuild the cached LLM client from the reset values so a deleted
        # llm_api_key can't keep serving generate requests.
        update_llm_config(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    return {"status": "ok"}
