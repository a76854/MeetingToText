import pytest

from backend.app.logging_config import build_log_config


@pytest.mark.unit
def test_root_and_uvicorn_loggers_configured_at_given_level() -> None:
    cfg = build_log_config("INFO", "/tmp/test.log")
    assert cfg["root"]["level"] == "INFO"  # type: ignore[index]
    assert cfg["loggers"]["uvicorn"]["level"] == "INFO"  # type: ignore[index]
    assert cfg["loggers"]["uvicorn.error"]["level"] == "INFO"  # type: ignore[index]
    assert cfg["loggers"]["uvicorn.access"]["level"] == "INFO"  # type: ignore[index]
    assert cfg["root"]["handlers"] == cfg["loggers"]["uvicorn"]["handlers"]  # type: ignore[index]


@pytest.mark.unit
def test_console_only_when_log_file_none_and_console_true() -> None:
    cfg = build_log_config("DEBUG", None, console=True)
    handlers = cfg["handlers"]  # type: ignore[assignment]
    assert "console" in handlers  # type: ignore[operator]
    assert "rotating_file" not in handlers  # type: ignore[operator]
    assert cfg["root"]["handlers"] == ["console"]  # type: ignore[index]
    # formatter present and readable
    assert "readable" in cfg["formatters"]  # type: ignore[operator]
    fmt = cfg["formatters"]["readable"]["format"]  # type: ignore[index]
    assert "asctime" in fmt and "levelname" in fmt and "message" in fmt


@pytest.mark.unit
def test_file_handler_added_when_log_file_given() -> None:
    cfg = build_log_config("WARNING", "/tmp/app.log")
    handlers = cfg["handlers"]  # type: ignore[assignment]
    assert "rotating_file" in handlers  # type: ignore[operator]
    assert "console" in handlers  # type: ignore[operator]
    rf = handlers["rotating_file"]  # type: ignore[index]
    assert rf["class"] == "logging.handlers.RotatingFileHandler"
    assert rf["maxBytes"] == 10 * 1024 * 1024
    assert rf["backupCount"] == 5
    assert rf["encoding"] == "utf-8"
    assert rf["filename"] == "/tmp/app.log"
    assert "rotating_file" in cfg["root"]["handlers"]  # type: ignore[index]


@pytest.mark.unit
def test_pid_suffix_applied_before_log_extension() -> None:
    cfg = build_log_config("INFO", "/tmp/app.log", console=False, pid=12345)
    handlers = cfg["handlers"]  # type: ignore[assignment]
    rf = handlers["rotating_file"]  # type: ignore[index]
    assert rf["filename"] == "/tmp/app.12345.log"
    # also without .log extension
    cfg2 = build_log_config("INFO", "/tmp/mylog", console=False, pid=99)
    rf2 = cfg2["handlers"]["rotating_file"]  # type: ignore[index,assignment]
    assert rf2["filename"] == "/tmp/mylog.99"


@pytest.mark.unit
def test_console_false_omits_stream_handler() -> None:
    cfg = build_log_config("ERROR", "/tmp/app.log", console=False)
    handlers = cfg["handlers"]  # type: ignore[assignment]
    assert "console" not in handlers  # type: ignore[operator]
    assert "rotating_file" in handlers  # type: ignore[operator]
    assert cfg["root"]["handlers"] == ["rotating_file"]  # type: ignore[index]


@pytest.mark.unit
def test_level_normalized_and_formatter_readable() -> None:
    cfg = build_log_config("debug", "/tmp/x.log", console=True)
    assert cfg["root"]["level"] == "DEBUG"  # type: ignore[index]
    fmt = cfg["formatters"]["readable"]["format"]  # type: ignore[index]
    assert "%(asctime)s" in fmt
    assert "%(name)s" in fmt
    assert "%(levelname)s" in fmt
    assert "%(message)s" in fmt
    handlers = cfg["handlers"]  # type: ignore[assignment]
    assert handlers["console"]["stream"] == "ext://sys.stderr"  # type: ignore[index]
    assert cfg["version"] == 1
    assert cfg["disable_existing_loggers"] is False
