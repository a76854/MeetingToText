import sys
import os
import time
import threading
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from backend.app.config import settings
from backend.app.routers import upload, record, transcribe, generate, settings as settings_router, export, audio


@asynccontextmanager
async def _lifespan(app: FastAPI):
    loaded = _load_user_settings()
    if loaded:
        logger.info(f"Loaded {loaded} user setting(s) from DB")

    removed = _cleanup_orphan_files()
    if removed:
        logger.info(f"cleaned {removed} orphan file(s) from {settings.temp_dir}")

    _preload_models()
    yield


app = FastAPI(
    title="MeetingToText",
    description="会议录音转写与纪要生成系统",
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


_USER_SETTING_KEYS = {
    "llm_base_url": str,
    "llm_api_key": str,
    "llm_model": str,
    "llm_temperature": float,
    "llm_max_tokens": int,
    "asr_model_type": str,
    "asr_model_name": str,
    "streaming_asr_model_name": str,
}

_BOOL_KEYS = {"streaming_asr_enabled"}


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


def _preload_models() -> None:
    """Pre-load final ASR model + streaming ASR if enabled in settings."""
    def _load_streaming():
        if not settings.streaming_asr_enabled:
            return
        try:
            from backend.app.services.asr_streaming import StreamingASR
            StreamingASR.get_instance(settings.streaming_asr_model_name).load()
        except Exception as e:
            logger.error(f"streaming ASR preload failed: {e}")

    def _load_final():
        try:
            from backend.app.services.asr import get_asr
            get_asr(settings.asr_model_type, settings.asr_model_name)
            logger.info(f"final ASR model loaded: {settings.asr_model_name}")
        except Exception as e:
            logger.error(f"final ASR preload failed: {e}")

    threading.Thread(target=_load_streaming, daemon=True, name="preload-streaming").start()
    threading.Thread(target=_load_final, daemon=True, name="preload-final").start()


def main():
    uvicorn.run(
        "backend.app.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
