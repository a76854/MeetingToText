"""CLI entrypoint for MeetingToText.

``meetingtotext`` defaults to ``serve`` when no subcommand is given.

``--daemon`` / ``--stop`` are POSIX-only (fork + setsid + pidfile).
The ``serve`` subcommand itself stays cross-platform.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import os
import signal
import sys
import time

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
    if default_log_file is not None and default_log_file.strip() == "":
        default_log_file = None
    default_reload = _env_truthy("MTT_RELOAD")
    p.add_argument("--host", default=default_host, help="Bind host (env MTT_HOST)")
    p.add_argument("--port", type=_valid_port, default=default_port, help="Bind port (env MTT_PORT)")  # noqa: E501
    p.add_argument("--workers", type=_valid_workers, default=1, help="Uvicorn workers (int >=1, reload forces 1)")  # noqa: E501
    p.add_argument("--reload", action="store_true", default=default_reload, help="Enable auto-reload (env MTT_RELOAD=1/true/yes)")  # noqa: E501
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default=default_log_level, help="Log level (env MTT_LOG_LEVEL)")  # noqa: E501
    p.add_argument("--log-file", default=default_log_file, help="Log file path (env MTT_LOG_FILE); None means console-only")  # noqa: E501
    p.add_argument(
        "--daemon",
        action="store_true",
        default=False,
        help="Run as daemon (POSIX-only, double-fork)",
    )
    p.add_argument("--pidfile", default="data/meetingtotext.pid", help="Pidfile for daemon mode")
    p.add_argument("--stop", action="store_true", default=False, help="Stop daemon via pidfile")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meetingtotext", description="MeetingToText — serve mode by default; use 'serve' subcommand for options.")  # noqa: E501
    _add_serve_args(parser)
    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser("serve", help="Run the API server (default)")
    _add_serve_args(serve_parser)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "reload", False) and getattr(args, "daemon", False):
        parser.error("--daemon cannot be combined with --reload")
    if getattr(args, "daemon", False) and not hasattr(os, "fork"):
        parser.error("daemon mode requires a POSIX platform")
    if hasattr(args, "log_level") and isinstance(args.log_level, str):
        args.log_level = args.log_level.upper()
    return args


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError as exc:
        return exc.errno != errno.ESRCH
    else:
        return True


def _handle_pidfile_before_fork(pidfile: str) -> None:
    if not os.path.exists(pidfile):
        return
    try:
        with open(pidfile) as f:
            pid = int(f.read().strip())
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(pidfile)
        return
    if _pid_alive(pid):
        build_parser().error(f"already running (pid {pid})")
    else:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(pidfile)


def _run_daemon(args: argparse.Namespace) -> None:
    pidfile: str = args.pidfile or "data/meetingtotext.pid"
    _handle_pidfile_before_fork(pidfile)
    try:
        first_pid = os.fork()
    except OSError as exc:
        print(f"fork failed: {exc}", file=sys.stderr)
        sys.exit(1)
    if first_pid != 0:
        time.sleep(0.2)
        print(f"started (pid {first_pid})")
        sys.stdout.flush()
        os._exit(0)
    with contextlib.suppress(OSError):
        os.setsid()
    try:
        second_pid = os.fork()
    except OSError as exc:
        print(f"second fork failed: {exc}", file=sys.stderr)
        os._exit(1)
    if second_pid != 0:
        os._exit(0)
    log_file_path: str = (
        args.log_file if args.log_file is not None else "data/logs/meetingtotext.log"
    )
    log_dir = os.path.dirname(log_file_path) or "."
    with contextlib.suppress(Exception):
        os.makedirs(log_dir, exist_ok=True)
    # Build central logging config: rotating file handler is the single writer,
    # console disabled to avoid duplication via fd-redirected stderr.
    from backend.app.logging_config import build_log_config

    daemon_log_config = build_log_config(
        args.log_level, log_file_path, console=False, pid=os.getpid()
    )
    # Resolve actual file the handler will write (pid-suffixed) and also
    # redirect stdio there so non-logging output lands alongside logs.
    # The handlers dict always contains "rotating_file" when log_file is set.
    try:
        _handlers = daemon_log_config.get("handlers", {})
        assert isinstance(_handlers, dict)
        _rf = _handlers.get("rotating_file")
        assert isinstance(_rf, dict)
        _handler_file = str(_rf.get("filename", log_file_path))
    except Exception:
        _handler_file = log_file_path
    # Ensure handler file's directory exists (build_log_config already tries,
    # but we handle pid case explicitly).
    with contextlib.suppress(Exception):
        os.makedirs(os.path.dirname(_handler_file) or ".", exist_ok=True)
    try:
        log_fd = os.open(_handler_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    except OSError as exc:
        print(f"cannot open log file {_handler_file}: {exc}", file=sys.stderr)
        os._exit(1)
    try:
        devnull_fd = os.open(os.devnull, os.O_RDWR)
    except OSError:
        devnull_fd = None
    try:
        if devnull_fd is not None:
            os.dup2(devnull_fd, 0)
            if devnull_fd not in (0, 1, 2, log_fd):
                os.close(devnull_fd)
        os.dup2(log_fd, 1)
        os.dup2(log_fd, 2)
        if log_fd not in (1, 2):
            os.close(log_fd)
        with contextlib.suppress(Exception):
            sys.stdin = open(os.devnull)  # noqa: SIM115  # daemon keeps fd open for process lifetime
        with contextlib.suppress(Exception):
            lf = open(_handler_file, "a", buffering=1)  # noqa: SIM115  # daemon keeps fd open for process lifetime
            sys.stdout = lf
            sys.stderr = lf
    except OSError:
        pass
    pid_dir = os.path.dirname(pidfile) or "."
    with contextlib.suppress(Exception):
        os.makedirs(pid_dir, exist_ok=True)
    try:
        with open(pidfile, "w") as pf:
            pf.write(str(os.getpid()))
    except OSError as exc:
        print(f"cannot write pidfile {pidfile}: {exc}", file=sys.stderr)
        os._exit(1)
    from backend.app.server import serve

    try:
        serve(
            host=args.host,
            port=args.port,
            workers=1,
            reload=False,
            log_level=args.log_level,
            log_file=_handler_file,
            log_config=daemon_log_config,
        )
    except BaseException:
        try:
            import traceback

            with open(_handler_file, "a") as fh:
                traceback.print_exc(file=fh)
        except Exception:
            pass
        os._exit(1)
    os._exit(0)


def _run_stop(args: argparse.Namespace) -> None:
    pidfile: str = args.pidfile or "data/meetingtotext.pid"
    if not os.path.exists(pidfile):
        print("not running")
        sys.exit(1)
    try:
        with open(pidfile) as f:
            pid = int(f.read().strip())
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(pidfile)
        print("not running")
        sys.exit(1)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(pidfile)
        sys.exit(0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(pidfile)
            sys.exit(0)
        print(f"cannot signal pid {pid}: {exc}", file=sys.stderr)
        sys.exit(1)
    for _ in range(25):
        time.sleep(0.2)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                break
            continue
        else:
            continue
    else:
        print(f"process {pid} did not stop", file=sys.stderr)
        sys.exit(1)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(pidfile)
    sys.exit(0)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if getattr(args, "daemon", False):
        _run_daemon(args)
        return
    if getattr(args, "stop", False):
        _run_stop(args)
        return
    from backend.app.logging_config import build_log_config
    from backend.app.server import serve

    cfg = build_log_config(args.log_level, args.log_file)
    serve(
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        log_level=args.log_level,
        log_file=args.log_file,
        log_config=cfg,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
