"""Boot-time jobs executed by the FastAPI lifespan in `server.py`.

`server.py` is assembly-only: it wires routers, middleware, and static hosting.
Everything that must run once per process start lives here and is awaited or
called, in order, by the lifespan:

1. `load_user_settings`  — settings bootstrap: copy user-persisted values from
   the SQLite store onto the runtime settings object (and refresh LLM config).
2. `cleanup_orphan_files` — janitor: delete temp files left behind by previous
   runs that are older than a day.
3. `recover_orphan_tasks` — crash recovery: mark tasks stuck in "processing"
   (e.g. after a hard kill / server restart) as errored.
4. `preload_models`       — model warmup: load the streaming ASR model up front
   (when enabled) so the first request doesn't pay the load cost.
"""

import os
import time
import asyncio
import logging

from backend.app.config import settings

logger = logging.getLogger(__name__)


_USER_SETTING_KEYS = {
    "llm_base_url": str,
    "llm_api_key": str,
    "llm_model": str,
    "llm_temperature": float,
    "llm_max_tokens": int,
    "asr_model_type": str,
    "asr_model_name": str,
    "ncpu": int,
    "asr_batch_size_s": int,
    "asr_merge_length_s": float,
    "asr_max_single_segment_time": int,
    "streaming_asr_model_name": str,
    "reconnect_grace_seconds": int,
    "audio_source": str,
}

_BOOL_KEYS = {"asr_needs_punc", "streaming_asr_enabled", "browser_noise_suppression", "asr_merge_vad"}


def load_user_settings() -> int:
    from backend.app.services.store import get_store
    from backend.app.services.llm import update_llm_config
    store = get_store()
    loaded = 0
    for key, caster in _USER_SETTING_KEYS.items():
        raw = store.get_setting(key)
        if not raw:
            continue
        try:
            value = caster(raw)
        except (TypeError, ValueError):
            continue
        setattr(settings, key, value)
        loaded += 1
    for key in _BOOL_KEYS:
        raw = store.get_setting(key)
        if raw:
            setattr(settings, key, raw.lower() == "true")
            loaded += 1
    if settings.llm_api_key and settings.llm_base_url and settings.llm_model:
        update_llm_config(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    return loaded


def cleanup_orphan_files(max_age_seconds: int = 24 * 3600) -> int:
    now = time.time()
    removed = 0
    for directory in (settings.temp_dir,):
        if not os.path.isdir(directory):
            continue
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            try:
                if os.path.isfile(path) and now - os.path.getmtime(path) > max_age_seconds:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
    return removed


def recover_orphan_tasks() -> int:
    from backend.app.services.store import get_store
    return get_store().mark_orphan_processing()


async def preload_models() -> None:
    """Pre-load streaming ASR model if enabled; final ASR loads on demand.

    Awaited from the lifespan instead of a fire-and-forget daemon thread so a
    uvicorn reload cannot kill a half-finished load mid-startup. Idempotent:
    StreamingASR.load() is guarded by its own lock + None-check, and an
    already-loaded singleton short-circuits, so repeated lifespans (reload)
    never duplicate loads or leave partial state behind.
    """
    if not settings.streaming_asr_enabled:
        return
    try:
        from backend.app.services.asr_streaming import StreamingASR
        instance = StreamingASR.get_instance(settings.streaming_asr_model_name)
        if instance.model is not None:
            logger.info("streaming ASR model already loaded; skipping preload")
            return
        await asyncio.to_thread(instance.load)
    except Exception as e:
        logger.error(f"streaming ASR preload failed: {e}")
