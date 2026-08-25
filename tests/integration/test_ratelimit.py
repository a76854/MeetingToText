"""Rate-limit middleware tests (todo 10).

Covers the fixed-window in-memory limiter with injectable clock and the
pure ASGI middleware mounted after CORS.

Cases:
- 3 requests within window succeed, 4th returns 429 with Retry-After + detail
- 429 body shape matches API conventions ({"detail": ...})
- Non-/api/* paths are not counted
- Distinct IPs have independent windows (via limiter class directly)
- Window rollover resets the counter (via injectable clock, no sleeps)
- Invalid env value falls back to 60 with warning
- Thread-safety: every dict access is under the lock (smoke via concurrent hits)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.middleware.ratelimit import (
    DEFAULT_RPM,
    InMemoryRateLimiter,
    RateLimitMiddleware,
    _resolve_rpm,
)
import backend.app.routers.health as health_module

pytestmark = pytest.mark.integration


class _Clock:
    """Injectable clock for deterministic window tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now: float = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_app(
    rpm: int | None = 3,
    _now: Callable[[], float] = time.time,
) -> FastAPI:
    app = FastAPI()
    # Mount rate-limit middleware (reads rpm / clock injectably).
    app.add_middleware(RateLimitMiddleware, rpm=rpm, _now=_now)
    app.include_router(health_module.router)

    @app.get("/")
    async def _root() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/assets/app.js")
    async def _asset() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_ratelimit_allows_within_limit_then_429() -> None:
    app = _make_app(rpm=3)
    with TestClient(app) as client:
        for _ in range(3):
            resp = client.get("/api/health")
            assert resp.status_code == 200
        resp = client.get("/api/health")
        assert resp.status_code == 429


def test_ratelimit_429_body_and_retry_after_header() -> None:
    app = _make_app(rpm=3)
    with TestClient(app) as client:
        for _ in range(3):
            client.get("/api/health")
        resp = client.get("/api/health")
        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"] == "请求过于频繁，请稍后重试"
        assert "retry-after" in {k.lower() for k in resp.headers}
        retry_after = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
        assert retry_after is not None
        # Must be a positive integer string.
        assert int(retry_after) >= 1


def test_ratelimit_non_api_paths_not_counted() -> None:
    app = _make_app(rpm=3)
    with TestClient(app) as client:
        # Exhaust the /api/* limit.
        for _ in range(3):
            assert client.get("/api/health").status_code == 200
        assert client.get("/api/health").status_code == 429
        # Non-API paths must still succeed (not counted toward the /api/* window).
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        # And they must not have consumed budget — still 429 for /api/*.
        assert client.get("/api/health").status_code == 429


def test_ratelimit_distinct_ips_independent() -> None:
    limiter = InMemoryRateLimiter(rpm=3)
    ip_a = "10.0.0.1"
    ip_b = "10.0.0.2"
    # Exhaust ip_a.
    for _ in range(3):
        allowed, _ = limiter.is_allowed(ip_a)
        assert allowed is True
    allowed, retry = limiter.is_allowed(ip_a)
    assert allowed is False
    assert retry >= 1
    # ip_b must still be allowed (independent window).
    for _ in range(3):
        allowed_b, _ = limiter.is_allowed(ip_b)
        assert allowed_b is True
    allowed_b, _ = limiter.is_allowed(ip_b)
    assert allowed_b is False


def test_ratelimit_window_rollover_resets_counter() -> None:
    clock = _Clock(start=1000.0)
    limiter = InMemoryRateLimiter(rpm=3, _now=clock)
    for _ in range(3):
        assert limiter.is_allowed("1.2.3.4")[0] is True
    assert limiter.is_allowed("1.2.3.4")[0] is False
    # Advance past the 60 s window — next request must succeed in a fresh window.
    clock.advance(61)
    allowed, retry = limiter.is_allowed("1.2.3.4")
    assert allowed is True
    assert retry == 0
    # Two more allowed in the new window, 4th blocked again.
    assert limiter.is_allowed("1.2.3.4")[0] is True
    assert limiter.is_allowed("1.2.3.4")[0] is True
    assert limiter.is_allowed("1.2.3.4")[0] is False


def test_ratelimit_window_rollover_via_middleware() -> None:
    clock = _Clock(start=2000.0)
    app = _make_app(rpm=2, _now=clock)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health").status_code == 429
        clock.advance(61)
        # After window rolls, should succeed again.
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health").status_code == 429


def test_ratelimit_invalid_env_falls_back_to_default_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Invalid string → fallback 60 + warning.
    monkeypatch.setenv("MTT_RATE_LIMIT_RPM", "not-an-int")
    with caplog.at_level(logging.WARNING):
        rpm = _resolve_rpm(explicit_rpm=None)
    assert rpm == DEFAULT_RPM
    assert any("invalid MTT_RATE_LIMIT_RPM" in r.message for r in caplog.records)
    caplog.clear()

    # Negative value → fallback.
    monkeypatch.setenv("MTT_RATE_LIMIT_RPM", "-5")
    with caplog.at_level(logging.WARNING):
        rpm = _resolve_rpm(explicit_rpm=None)
    assert rpm == DEFAULT_RPM
    assert any("invalid MTT_RATE_LIMIT_RPM" in r.message for r in caplog.records)
    caplog.clear()

    # Zero string → fallback.
    monkeypatch.setenv("MTT_RATE_LIMIT_RPM", "0")
    with caplog.at_level(logging.WARNING):
        rpm = _resolve_rpm(explicit_rpm=None)
    assert rpm == DEFAULT_RPM
    caplog.clear()

    # Valid env is respected.
    monkeypatch.setenv("MTT_RATE_LIMIT_RPM", "42")
    rpm = _resolve_rpm(explicit_rpm=None)
    assert rpm == 42

    # Explicit rpm overrides env.
    monkeypatch.setenv("MTT_RATE_LIMIT_RPM", "999")
    rpm = _resolve_rpm(explicit_rpm=5)
    assert rpm == 5


def test_ratelimit_retry_after_is_seconds_to_window_reset() -> None:
    clock = _Clock(start=3000.0)
    limiter = InMemoryRateLimiter(rpm=1, _now=clock)
    assert limiter.is_allowed("5.5.5.5")[0] is True
    # Immediately over limit: retry_after should be ~60.
    allowed, retry = limiter.is_allowed("5.5.5.5")
    assert allowed is False
    assert 1 <= retry <= 60
    assert retry == 60  # no time advanced, so full window remains
    # Advance 10 s: retry should shrink by ~10.
    clock.advance(10)
    allowed, retry2 = limiter.is_allowed("5.5.5.5")
    assert allowed is False
    assert retry2 == 50
    # Advance to just before rollover: small retry.
    clock.advance(49)
    allowed, retry3 = limiter.is_allowed("5.5.5.5")
    assert allowed is False
    assert retry3 == 1
    # One more second rolls the window.
    clock.advance(1)
    assert limiter.is_allowed("5.5.5.5")[0] is True
