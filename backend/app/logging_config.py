"""Central logging dictConfig for MeetingToText.

Builds a single ``logging.config.dictConfig``-compatible dictionary that
covers both the application ROOT logger and the ``uvicorn.*`` loggers so
that ``logger.info`` calls and uvicorn access/error logs flow through ONE
config.

Reload resilience:
    Because the dict is passed as ``uvicorn.run(log_config=...)``, reload
    subprocesses re-apply it — the root RotatingFileHandler survives reloads
    (uvicorn re-invokes dictConfig in the reloaded process).

Workers>1 isolation hook:
    When ``pid`` is not None, ``".{pid}"`` is inserted before the ``.log``
    extension so each worker writes to its own file (avoids interleaved
    writes without a shared handler).
"""

from __future__ import annotations

import contextlib
import os


def _resolve_log_file(log_file: str, pid: int | None) -> str:
    if pid is None:
        return log_file
    base, ext = os.path.splitext(log_file)
    if ext == ".log":
        return f"{base}.{pid}.log"
    # No .log extension — just append .{pid}
    return f"{log_file}.{pid}"


def build_log_config(
    level: str,
    log_file: str | None,
    *,
    console: bool = True,
    pid: int | None = None,
) -> dict:
    """Return a dictConfig-compatible dictionary.

    Args:
        level: Log level name (e.g. "INFO", "DEBUG").
        log_file: File path for RotatingFileHandler, or None for console-only.
        console: Whether to include a StreamHandler(stderr).
        pid: When not None, suffix the log file with ``.{pid}`` before ``.log``.
    """
    lvl = level.upper() if isinstance(level, str) else "INFO"
    if lvl not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        lvl = "INFO"

    formatter_name = "readable"
    formatters: dict[str, dict[str, str]] = {
        formatter_name: {
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    }

    handlers: dict[str, dict[str, object]] = {}
    handler_names: list[str] = []

    if console:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "level": lvl,
            "formatter": formatter_name,
            "stream": "ext://sys.stderr",
        }
        handler_names.append("console")

    if log_file is not None:
        resolved = _resolve_log_file(log_file, pid)
        # Ensure directory exists at build time (best-effort; handler will
        # also create on open if missing).
        log_dir = os.path.dirname(resolved) or "."
        with contextlib.suppress(Exception):
            os.makedirs(log_dir, exist_ok=True)
        handlers["rotating_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": lvl,
            "formatter": formatter_name,
            "filename": resolved,
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        }
        handler_names.append("rotating_file")

    # Fallback: if neither handler (console=False, log_file=None) keep at
    # least console to avoid empty handler list.
    if not handler_names:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "level": lvl,
            "formatter": formatter_name,
            "stream": "ext://sys.stderr",
        }
        handler_names = ["console"]

    config: dict[str, object] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "handlers": handlers,
        "root": {
            "level": lvl,
            "handlers": handler_names,
        },
        "loggers": {
            "uvicorn": {
                "level": lvl,
                "handlers": handler_names,
                "propagate": False,
            },
            "uvicorn.error": {
                "level": lvl,
                "handlers": handler_names,
                "propagate": False,
            },
            "uvicorn.access": {
                "level": lvl,
                "handlers": handler_names,
                "propagate": False,
            },
        },
    }
    return config
