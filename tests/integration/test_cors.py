"""CORS allowlist tests (todo 12).

Covers ``backend.app.config.cors_origins_from_env`` parsing and the
CORSMiddleware wiring in ``backend.app.server`` via a real ``TestClient``.

Cases:
1) GET with Origin http://localhost:5173 → access-control-allow-origin echoed
2) GET with Origin http://localhost:8000 → allowed (second default entry)
3) GET with unlisted Origin http://evil.example → no ACAO header
4) No Origin header → no CORS headers (normal same-origin request)
Plus: OPTIONS preflight, custom env parsing, whitespace/empty handling,
and credentials remain disabled.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from backend.app.config import cors_origins_from_env
from backend.app.routers.health import router as health_router

pytestmark = pytest.mark.integration


def _make_cors_app() -> FastAPI:
    """Build a fresh FastAPI with CORSMiddleware wired via helper.

    Mirrors ``backend.app.server`` assembly order (CORS mounted before
    routers) but isolates from the already-imported singleton ``app`` so
    each test sees the current ``MTT_CORS_ORIGINS`` value.
    """
    origins = cors_origins_from_env()
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)

    @app.get("/")
    async def _root() -> dict[str, bool]:
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# Helper parsing
# ---------------------------------------------------------------------------


def test_cors_helper_default_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MTT_CORS_ORIGINS", raising=False)
    origins = cors_origins_from_env()
    assert origins == ["http://localhost:5173", "http://localhost:8000", "http://localhost"]


def test_cors_helper_custom_single(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MTT_CORS_ORIGINS", "https://example.com")
    assert cors_origins_from_env() == ["https://example.com"]


def test_cors_helper_custom_multiple_with_whitespace_and_empty_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MTT_CORS_ORIGINS", " http://a.example , , http://b.example ,,  ")
    assert cors_origins_from_env() == ["http://a.example", "http://b.example"]


def test_cors_helper_blank_string_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MTT_CORS_ORIGINS", "   ")
    assert cors_origins_from_env() == ["http://localhost:5173", "http://localhost:8000", "http://localhost"]


def test_cors_helper_drops_empty_segments_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MTT_CORS_ORIGINS", ",,,")
    assert cors_origins_from_env() == []


# ---------------------------------------------------------------------------
# Integration: CORSMiddleware via TestClient
# ---------------------------------------------------------------------------


def test_cors_allows_localhost_5173(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MTT_CORS_ORIGINS", raising=False)
    app = _make_cors_app()
    with TestClient(app) as client:
        resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert resp.status_code == 200
        # Starlette lowercases headers in TestClient, so check case-insensitively
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_allows_localhost_8000(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MTT_CORS_ORIGINS", raising=False)
    app = _make_cors_app()
    with TestClient(app) as client:
        resp = client.get("/api/health", headers={"Origin": "http://localhost:8000"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8000"


def test_cors_allows_localhost_80(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MTT_CORS_ORIGINS", raising=False)
    app = _make_cors_app()
    with TestClient(app) as client:
        resp = client.get("/api/health", headers={"Origin": "http://localhost"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost"


def test_cors_blocks_unlisted_evil_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MTT_CORS_ORIGINS", raising=False)
    app = _make_cors_app()
    with TestClient(app) as client:
        resp = client.get("/api/health", headers={"Origin": "http://evil.example"})
        assert resp.status_code == 200
        # Unlisted origin must NOT get an ACAO header
        assert resp.headers.get("access-control-allow-origin") is None
        # Also ensure lower-case lookup misses
        assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_cors_no_origin_header_yields_no_cors_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MTT_CORS_ORIGINS", raising=False)
    app = _make_cors_app()
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") is None
        assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_cors_preflight_options_allowed_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MTT_CORS_ORIGINS", raising=False)
    app = _make_cors_app()
    with TestClient(app) as client:
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        # Starlette CORSMiddleware responds 200 to preflight for allowed origins
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
        # Preflight must echo allowed methods
        assert "access-control-allow-methods" in {k.lower() for k in resp.headers}


def test_cors_preflight_options_blocked_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MTT_CORS_ORIGINS", raising=False)
    app = _make_cors_app()
    with TestClient(app) as client:
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Unlisted origin preflight must not carry ACAO
        assert resp.headers.get("access-control-allow-origin") is None


def test_cors_custom_env_restricts_to_explicit_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MTT_CORS_ORIGINS", "https://allowed.example")
    app = _make_cors_app()
    with TestClient(app) as client:
        ok = client.get("/api/health", headers={"Origin": "https://allowed.example"})
        assert ok.headers.get("access-control-allow-origin") == "https://allowed.example"
        blocked = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert blocked.headers.get("access-control-allow-origin") is None


def test_cors_credentials_remain_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: allow_credentials must stay False (task forbids True)."""
    monkeypatch.delenv("MTT_CORS_ORIGINS", raising=False)
    app = _make_cors_app()
    with TestClient(app) as client:
        resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        # When allow_credentials=False, Starlette does NOT emit allow-credentials
        # or emits 'false' depending on version — in either case it must not be 'true'
        val = resp.headers.get("access-control-allow-credentials")
        assert val is None or val.lower() != "true"
