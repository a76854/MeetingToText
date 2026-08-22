import sys
import os
import time
import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from backend.app.config import settings
from backend.app.routers import upload, record, transcribe, generate, settings as settings_router, export, audio
from backend.app.services.pipeline import pipeline_executor


@asynccontextmanager
async def _lifespan(app: FastAPI):
    loaded = _load_user_settings()
    if loaded:
        logger.info(f"Loaded {loaded} user setting(s) from DB")

    removed = _cleanup_orphan_files()
    if removed:
        logger.info(f"cleaned {removed} orphan file(s) from {settings.temp_dir}")

    orphaned = _recover_orphan_tasks()
    if orphaned:
        logger.info(f"marked {orphaned} orphaned task(s) as error (server restart)")

    await _preload_models()
    yield
    pipeline_executor.shutdown(wait=True)


app = FastAPI(
    title="MeetingToText",
    description="会议录音转写与纪要生成系统",
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(record.router)
app.include_router(transcribe.router)
app.include_router(generate.router)
app.include_router(settings_router.router)
app.include_router(export.router)
app.include_router(audio.router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "llm_configured": bool(settings.llm_api_key),
        "asr_model": settings.asr_model_type,
    }


frontend_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")
_index_path = os.path.join(frontend_dist, "index.html")

if os.path.isdir(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/")
    async def root_fallback():
        return FileResponse(_index_path)

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Defensive: reject explicit parent-directory segments outright.
        if any(part == ".." for part in full_path.replace("\\", "/").split("/")):
            return FileResponse(_index_path)
        file_path = os.path.realpath(os.path.join(frontend_dist, full_path))
        dist_root = os.path.realpath(frontend_dist)
        if (
            full_path
            and os.path.isfile(file_path)
            and file_path.startswith(dist_root + os.sep)
        ):
            return FileResponse(file_path)
        return FileResponse(_index_path)


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


def _load_user_settings() -> int:
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


def _cleanup_orphan_files(max_age_seconds: int = 24 * 3600) -> int:
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


def _recover_orphan_tasks() -> int:
    from backend.app.services.store import get_store
    return get_store().mark_orphan_processing()


async def _preload_models() -> None:
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


def main():
    uvicorn.run(
        "backend.app.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "backend")],
    )


if __name__ == "__main__":
    main()
