"""Readiness probe endpoint.

Live checks:
- DB: SELECT 1 against SQLite (sqlite3.connect timeout=2)
- Disk: free space via shutil.disk_usage(settings.data_dir)
Model preload state does NOT affect readiness.
"""

import os
import shutil
import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.app.config import settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> JSONResponse:
    # -- DB probe ----------------------------------------------------------
    db_status = "ok"
    try:
        conn = sqlite3.connect(settings.db_path, timeout=2)
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
    except Exception:
        db_status = "error"

    # -- Disk probe --------------------------------------------------------
    try:
        raw = os.getenv("MTT_HEALTH_MIN_DISK_MB", "100")
        try:
            min_disk_mb = int(raw)
        except ValueError:
            min_disk_mb = 100
        free_bytes = shutil.disk_usage(settings.data_dir).free
        free_mb = free_bytes // (1024 * 1024)
        disk_status = "ok" if free_mb >= min_disk_mb else "low"
    except Exception:
        # If disk_usage itself fails treat as low and report 0 free.
        free_mb = 0
        disk_status = "low"
        # Re-compute free_mb for response if possible; fallback 0 already set
        try:
            free_mb = shutil.disk_usage(settings.data_dir).free // (1024 * 1024)
        except Exception:
            free_mb = 0

    # -- Config echo -------------------------------------------------------
    llm_configured = bool(settings.llm_api_key)
    asr_model = settings.asr_model_type

    healthy = db_status == "ok" and disk_status == "ok"
    status = "ok" if healthy else "unhealthy"
    http_code = 200 if healthy else 503

    body: dict[str, object] = {
        "status": status,
        "db": db_status,
        "disk": disk_status,
        "disk_free_mb": free_mb,
        "llm_configured": llm_configured,
        "asr_model": asr_model,
    }
    return JSONResponse(content=body, status_code=http_code)
