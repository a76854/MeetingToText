"""CLI entrypoint for MeetingToText.

``meetingtotext`` / ``python main.py`` default to ``serve`` when no subcommand
is given, preserving the historical ``python main.py`` behaviour.

Future ``--daemon`` / ``--stop`` are POSIX-only (fork + setsid + pidfile).
The ``serve`` subcommand itself stays cross-platform.
"""

from __future__ import annotations

import argparse
import os
import sys

_TRUTHY = {"1", "true", "yes"}


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUTHY


def _valid_port(value: str) -> int:
    iv = int(value)
    if not 1 <= iv <= 65535:
        raise argparse.ArgumentTypeError("port must be 1-65535")
    return iv


def _valid_workers(value: str) -> int:
    iv = int(value)
    if iv < 1:
        raise argparse.ArgumentTypeError("workers must be >= 1")
    return iv


def _add_serve_args(p: argparse.ArgumentParser) -> None:
    default_host = os.getenv("MTT_HOST", "127.0.0.1")
    default_port_raw = os.getenv("MTT_PORT", "8000")
    try:
        default_port = int(default_port_raw)
    except ValueError:
        default_port = 8000
    default_log_level = os.getenv("MTT_LOG_LEVEL", "INFO").strip().upper() or "INFO"
    if default_log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        default_log_level = "INFO"
    default_log_file = os.getenv("MTT_LOG_FILE")
    # Treat empty env as None (console-only)
    if default_log_file is not None and default_log_file.strip() == "":
        default_log_file = None
    default_reload = _env_truthy("MTT_RELOAD")

    p.add_argument("--host", default=default_host, help="Bind host (env MTT_HOST)")
    p.add_argument(
        "--port",
        type=_valid_port,
        default=default_port,
        help="Bind port (env MTT_PORT)",
    )
    p.add_argument(
        "--workers",
        type=_valid_workers,
        default=1,
        help="Uvicorn workers (int >=1, reload forces 1)",
    )
    p.add_argument(
        "--reload",
        action="store_true",
        default=default_reload,
        help="Enable auto-reload (env MTT_RELOAD=1/true/yes)",
    )
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=default_log_level,
        help="Log level (env MTT_LOG_LEVEL)",
    )
    p.add_argument(
        "--log-file",
        default=default_log_file,
        help="Log file path (env MTT_LOG_FILE); None means console-only",
    )
    p.add_argument(
        "--daemon",
        action="store_true",
        default=False,
        help="[FUTURE POSIX-only] run as daemon (next iteration)",
    )
    p.add_argument(
        "--pidfile",
        default="data/meetingtotext.pid",
        help="Pidfile for daemon mode",
    )
    p.add_argument(
        "--stop",
        action="store_true",
        default=False,
        help="[FUTURE] stop daemon (next iteration)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meetingtotext",
        description="MeetingToText — serve mode by default; use 'serve' subcommand for options.",
    )
    _add_serve_args(parser)

    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser("serve", help="Run the API server (default)")
    _add_serve_args(serve_parser)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Mutual-exclusion / future-gate validation (must use parser.error => exit 2)
    if getattr(args, "reload", False) and getattr(args, "daemon", False):
        parser.error("--daemon cannot be combined with --reload")
    if getattr(args, "daemon", False):
        parser.error("daemon mode lands in the next iteration")
    if getattr(args, "stop", False):
        parser.error("stop lands in the next iteration")

    # Normalize log_level upper (argparse already validates choices are upper)
    if hasattr(args, "log_level") and isinstance(args.log_level, str):
        args.log_level = args.log_level.upper()

    return args


def main(argv: list[str] | None = None) -> None:
    # Strip leading "serve" if present so that both `meetingtotext` and
    # `meetingtotext serve` share the same path; argparse already handles it
    # but we keep parse_args owning validation.
    args = parse_args(argv)

    # Lazy import to avoid circular import at module load.
    from backend.app.server import serve

    # Future consumers: todo-8 passes log_config=dictConfig result
    serve(
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        log_level=args.log_level,
        log_file=args.log_file,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
