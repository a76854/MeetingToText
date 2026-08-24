"""Readiness probe endpoint.

Reports whether the server is up and whether the LLM is configured, plus which
ASR engine is active. Kept as its own tiny router so server.py stays a pure
assembly module.
"""

from fastapi import APIRouter

from backend.app.config import settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "llm_configured": bool(settings.llm_api_key),
        "asr_model": settings.asr_model_type,
    }
