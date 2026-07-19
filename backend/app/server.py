import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from backend.app.config import PROJECT_ROOT, settings
from backend.app.routers import upload, record, transcribe, generate, settings as settings_router, export, audio

app = FastAPI(
    title="MeetingToText",
    description="会议录音转写与纪要生成系统",
    version="0.1.0",
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
}


def _parse_env_file(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not os.path.exists(path):
        return result
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    result[k] = v
    except OSError:
        pass
    return result


def _migrate_env_to_db() -> list[str]:
    env_path = os.path.join(PROJECT_ROOT, ".env")
    env_vars = _parse_env_file(env_path)
    if not env_vars:
        return []

    from backend.app.services.store import get_store
    store = get_store()
    migrated: list[str] = []
    for key in _USER_SETTING_KEYS:
        mtt_key = f"MTT_{key.upper()}"
        if mtt_key in env_vars and not store.get_setting(key):
            store.set_setting(key, env_vars[mtt_key])
            migrated.append(key)
    return migrated


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


@app.on_event("startup")
def on_startup():
    migrated = _migrate_env_to_db()
    if migrated:
        env_path = os.path.join(PROJECT_ROOT, ".env")
        print(f"[startup] Migrated from .env -> DB: {migrated}")
        print(f"[startup] You can now delete {env_path}")

    loaded = _load_user_settings()
    if loaded:
        print(f"[startup] Loaded {loaded} user setting(s) from DB")

    removed = _cleanup_orphan_files()
    if removed:
        print(f"[startup] cleaned {removed} orphan file(s) from {settings.temp_dir}")


def main():
    uvicorn.run(
        "backend.app.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
