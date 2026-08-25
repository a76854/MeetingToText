"""Assembly module: wires the FastAPI app together.

No business logic lives here. Responsibilities:

- create the FastAPI app and attach the bootstrap lifespan (boot jobs live in
  `backend.app.startup`);
- register CORS middleware;
- include every router (upload, record, transcribe, generate, settings,
  export, audio, health);
- serve the built SPA from `frontend/dist` with an index.html fallback;
- expose `main()` as the uvicorn entrypoint.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app import startup
from backend.app.config import settings
from backend.app.routers import audio, export, generate, record, transcribe, upload
from backend.app.routers import settings as settings_router
from backend.app.routers.health import router as health_router
from backend.app.services.pipeline import pipeline_executor


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # 1. Settings bootstrap: copy user-persisted values from the DB onto runtime config.
    loaded = startup.load_user_settings()
    if loaded:
        logger.info(f"Loaded {loaded} user setting(s) from DB")

    # 2. Janitor: drop temp files older than a day left behind by previous runs.
    removed = startup.cleanup_orphan_files()
    if removed:
        logger.info(f"cleaned {removed} orphan file(s) from {settings.temp_dir}")

    # 3. Crash recovery: mark tasks stuck in "processing" as errored (server restart).
    orphaned = startup.recover_orphan_tasks()
    if orphaned:
        logger.info(f"marked {orphaned} orphaned task(s) as error (server restart)")

    # 4. Model warmup: preload the streaming ASR model if enabled.
    await startup.preload_models()
    yield
    # Shutdown: stop the transcription pipeline executor's worker threads.
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
app.include_router(health_router)


frontend_dist = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist"
)
_index_path = os.path.join(frontend_dist, "index.html")

if os.path.isdir(frontend_dist):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(frontend_dist, "assets")),
        name="assets",
    )

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


def main():
    uvicorn.run(
        "backend.app.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "backend")
        ],
    )


if __name__ == "__main__":
    main()
