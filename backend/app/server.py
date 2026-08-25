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
from backend.app.config import cors_origins_from_env, settings
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
    allow_origins=cors_origins_from_env(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Rate limiting (todo 10): fixed-window in-memory; exact only with --workers 1 ---  # noqa: E501
from backend.app.middleware.ratelimit import RateLimitMiddleware  # noqa: E402

app.add_middleware(RateLimitMiddleware)

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


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    workers: int = 1,
    reload: bool = False,
    log_level: str = "INFO",
    log_file: str | None = None,
    log_config: dict | None = None,
) -> None:
    """Run uvicorn for the assembled app.

    Parameters are wired from :mod:`backend.app.cli` so that ``meetingtotext``
    / ``python main.py`` share a single code path. ``log_file`` is accepted
    for forward-compatibility (todo-8 wires a dictConfig); today it is unused
    beyond being part of the stable signature.
    """

    _ = log_file  # reserved for todo-8 dictConfig wiring
    kwargs: dict = {}
    if log_config is not None:
        kwargs["log_config"] = log_config
    uv_level = log_level.lower() if isinstance(log_level, str) else "info"
    run_kwargs: dict = {
        "host": host,
        "port": port,
        "workers": workers,
        "reload": reload,
        "log_level": uv_level,
    }
    run_kwargs.update(kwargs)
    if reload:
        run_kwargs["reload_dirs"] = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "backend")
        ]
    uvicorn.run("backend.app.server:app", **run_kwargs)


def main() -> None:
    """Thin alias — real entrypoint is :mod:`backend.app.cli`."""

    from backend.app.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
