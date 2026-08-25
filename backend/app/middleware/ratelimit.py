"""In-memory fixed-window rate-limit middleware (zero dependencies).

Contract:
    Per-process counters (``dict[ip] -> (window_start, count)``) guarded by a
    ``threading.Lock``.  Exact only with ``--workers 1`` (the project default);
    with ``workers>1`` each worker holds independent counters so the effective
    global limit is ``rpm * workers``.  Callers that need precise global
    enforcement must put an external gateway in front.

    Window: 60 s fixed.  Limit: ``MTT_RATE_LIMIT_RPM`` (int, default 60);
    invalid / missing / ``<=0`` falls back to 60 with a startup warning.

Design choice:
    Pure ASGI callable (``__call__(scope, receive, send)``) rather than
    ``BaseHTTPMiddleware``.  ``BaseHTTPMiddleware`` copies the entire body
    through an extra anyio task group — pure ASGI avoids that copy and keeps
    the hot path allocation-free.  Starlette dispatches pure ASGI middleware
    inline with no extra thread hop.

Thread-safety:
    Every ``dict`` read/write is under ``self._lock``.  Under CPython the GIL
    already serialises bytecode, but the explicit lock documents the invariant
    and keeps correctness on free-threaded (``--disable-gil``) builds.

Scope:
    Only ``/api/*`` HTTP requests are counted.  Static / SPA fallback paths
    bypass the limiter entirely so asset loads are never throttled.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RPM: int = 60
WINDOW_SECONDS: int = 60


def _resolve_rpm(explicit_rpm: int | None = None) -> int:
    """Resolve the RPM limit.

    Precedence: explicit ``rpm`` arg > ``MTT_RATE_LIMIT_RPM`` env > ``60``.
    Invalid / ``<=0`` values fall back to ``60`` with a warning.
    """
    if explicit_rpm is not None:
        if isinstance(explicit_rpm, int) and explicit_rpm > 0:
            return explicit_rpm
        logger.warning(
            "invalid explicit rpm=%r, falling back to %s",
            explicit_rpm,
            DEFAULT_RPM,
        )
        return DEFAULT_RPM
    raw = os.getenv("MTT_RATE_LIMIT_RPM", "")
    if raw.strip() == "":
        return DEFAULT_RPM
    try:
        parsed = int(raw.strip())
    except (ValueError, TypeError):
        logger.warning(
            "invalid MTT_RATE_LIMIT_RPM=%r, falling back to %s",
            raw,
            DEFAULT_RPM,
        )
        return DEFAULT_RPM
    if parsed <= 0:
        logger.warning(
            "invalid MTT_RATE_LIMIT_RPM=%r (must be >0), falling back to %s",
            raw,
            DEFAULT_RPM,
        )
        return DEFAULT_RPM
    return parsed


class InMemoryRateLimiter:
    """Fixed-window counter keyed by IP.

    Args:
        rpm: Maximum requests per ``window_seconds``.
        window_seconds: Window length (default 60).
        _now: Injectable clock for deterministic tests (default ``time.time``).
    """

    def __init__(
        self,
        rpm: int = DEFAULT_RPM,
        window_seconds: int = WINDOW_SECONDS,
        _now: Callable[[], float] = time.time,
    ) -> None:
        self.rpm: int = rpm if rpm > 0 else DEFAULT_RPM
        self.window_seconds: int = window_seconds
        self._now: Callable[[], float] = _now
        self._lock: threading.Lock = threading.Lock()
        self._store: dict[str, tuple[float, int]] = {}

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Check and record one request for *key*.

        Returns:
            (allowed, retry_after_seconds).  ``retry_after`` is 0 when
            allowed, otherwise seconds until the current window resets
            (ceil, at least 1).
        """
        now = self._now()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._store[key] = (now, 1)
                return True, 0
            window_start, count = entry
            elapsed = now - window_start
            if elapsed >= self.window_seconds:
                # Window rolled over — start a fresh window.
                self._store[key] = (now, 1)
                return True, 0
            if count < self.rpm:
                self._store[key] = (window_start, count + 1)
                return True, 0
            # Over limit — report seconds until window reset.
            retry_after = int(self.window_seconds - elapsed)
            if retry_after <= 0:
                retry_after = 1
            # Defensive: if floating rounding would give 0, clamp to 1 so
            # the header is always meaningful; if the window boundary is
            # exactly now the next request will roll the window.
            return False, retry_after

    def reset(self) -> None:
        """Clear all counters (test helper)."""
        with self._lock:
            self._store.clear()

    @property
    def store_size(self) -> int:
        """Number of tracked keys (test helper, under lock)."""
        with self._lock:
            return len(self._store)


class RateLimitMiddleware:
    """Pure ASGI rate-limit middleware.

    Counts only ``/api/*`` HTTP requests by client IP.  Over-limit returns
    ``429`` JSON with ``Retry-After``.

    Args:
        app: Downstream ASGI app.
        rpm: Override RPM (when ``None``, env ``MTT_RATE_LIMIT_RPM`` is read).
        _now: Injectable clock (passed to the underlying limiter).
    """

    def __init__(
        self,
        app: Any,
        rpm: int | None = None,
        _now: Callable[[], float] = time.time,
    ) -> None:
        self.app: Any = app
        resolved = _resolve_rpm(rpm)
        self.limiter: InMemoryRateLimiter = InMemoryRateLimiter(
            rpm=resolved, _now=_now
        )
        # ALWAYS emit one INFO line at mount so the single-worker caveat is
        # visible in logs regardless of workers CLI value (workers is a CLI arg,
        # not app state).
        logger.info(
            "rate limiting enabled: %s req/60s per IP (fixed-window, in-memory; "
            "exact only with --workers 1; workers>1 multiplies effective limit)",
            resolved,
        )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        if client is None:
            ip = "unknown"
        else:
            try:
                ip = str(client[0]) if client[0] else "unknown"
            except (IndexError, TypeError):
                ip = "unknown"
        allowed, retry_after = self.limiter.is_allowed(ip)
        if allowed:
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": "请求过于频繁，请稍后重试"}).encode("utf-8")
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"retry-after", str(retry_after).encode()),
        ]
        # Ensure CORS headers are present on 429 even though this middleware
        # is mounted AFTER CORSMiddleware (so it is outermost in Starlette's
        # stack and the inner CORS layer won't wrap its short-circuit
        # response).  Mirror the CORS allow-origin logic so 429s are not
        # opaque to browsers.
        origin: str | None = None
        for k, v in scope.get("headers") or []:
            if k.lower() == b"origin":
                try:
                    origin = v.decode("latin-1")
                except Exception:
                    origin = None
                break
        if origin is not None:
            raw_cors = os.getenv("MTT_CORS_ORIGINS", "*")
            # Current server.py hardcodes ["*"]; future todo 12 will set
            # MTT_CORS_ORIGINS="http://localhost:5173,http://localhost:8000".
            # Handle both: "*" means allow all, otherwise check allowlist.
            if raw_cors.strip() == "" or raw_cors.strip() == "*":
                headers.append((b"access-control-allow-origin", b"*"))
            else:
                allowlist = [o.strip() for o in raw_cors.split(",") if o.strip()]
                if origin in allowlist or "*" in allowlist:
                    headers.append(
                        (b"access-control-allow-origin", origin.encode("latin-1"))
                    )
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": headers,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
