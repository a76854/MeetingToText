"""Hermetic tests for cli.transcribe subcommand.

No model, no network, no sleeps. All IO faked via monkeypatch.
"""

from __future__ import annotations

import argparse
import os

import pytest

pytestmark = pytest.mark.unit

import cli
from backend.app.models.schemas import TaskInfo, TaskResult, TaskStatus, TranscriptSegment


def _make_done_task(task_id: str, filename: str, audio_path: str) -> TaskInfo:
    return TaskInfo(
        id=task_id,
        filename=filename,
        audio_path=audio_path,
        status=TaskStatus.done,
        result=TaskResult(
            segments=[TranscriptSegment(start=0, end=1, speaker="A", text="hello")],
            full_text="hello",
        ),
    )


def _patch_cli(monkeypatch, tmp_path=None):  # noqa: ANN001
    """Install fakes for pipeline and store; return call log dict."""
    calls: list[str] = []
    created: dict[str, TaskInfo] = {}
    counter = {"n": 0}

    def fake_create_task(filename: str, audio_path: str) -> TaskInfo:  # noqa: ANN001
        counter["n"] += 1
        tid = f"tid{counter['n']:03d}"
        t = TaskInfo(id=tid, filename=filename, audio_path=audio_path)
        created[tid] = t
        return t

    def fake_get_task(task_id: str) -> TaskInfo | None:  # noqa: ANN001
        orig = created.get(task_id)
        if orig is None:
            return None
        return _make_done_task(orig.id, orig.filename, orig.audio_path)

    def fake_run_pipeline(task_id: str) -> None:  # noqa: ANN001
        calls.append(task_id)

    monkeypatch.setattr("backend.app.services.store.create_task", fake_create_task)
    monkeypatch.setattr("backend.app.services.store.get_task", fake_get_task)
    monkeypatch.setattr("backend.app.services.pipeline.run_pipeline", fake_run_pipeline)
    return calls, created


def test_txt_written_to_stem_txt(monkeypatch, tmp_path, capsys):
    """Given a single wav, When transcribe --format txt, Then <stem>.txt exists with content and run_pipeline called correctly."""
    calls, _ = _patch_cli(monkeypatch)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFFfake")

    cli.main(["transcribe", str(wav), "--format", "txt"])

    out = tmp_path / "a.txt"
    assert out.exists(), "expected output at <stem>.txt"
    content = out.read_text(encoding="utf-8")
    # _export_txt joins "[A] hello" for our fake TaskResult
    assert content == "[A] hello"
    # misleading_success_output guard: run_pipeline must have been called with the task.id created
    assert calls == ["tid001"]
    assert "转录完成" in capsys.readouterr().out


def test_out_honored_and_format_inferred(monkeypatch, tmp_path, capsys):
    """Given --out /tmp/x.md with --format txt, When transcribe, Then md exporter wins (format inferred from extension)."""
    calls, _ = _patch_cli(monkeypatch)
    wav = tmp_path / "b.wav"
    wav.write_bytes(b"RIFFfake")
    out_path = tmp_path / "x.md"

    cli.main(["transcribe", str(wav), "--format", "txt", "--out", str(out_path)])

    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    # md exporter adds markdown header
    assert "# 会议转录" in content
    assert "[A] hello" not in content or "# " in content  # md wraps in headings
    assert "hello" in content
    assert calls == ["tid001"]


def test_multi_input_writes_n_files(monkeypatch, tmp_path, capsys):
    """Given two wavs, When transcribe without --out, Then N files written and N pipeline calls."""
    calls, _ = _patch_cli(monkeypatch)
    wav1 = tmp_path / "c1.wav"
    wav2 = tmp_path / "c2.wav"
    wav1.write_bytes(b"RIFF1")
    wav2.write_bytes(b"RIFF2")

    cli.main(["transcribe", str(wav1), str(wav2), "--format", "txt"])

    assert (tmp_path / "c1.txt").exists()
    assert (tmp_path / "c2.txt").exists()
    assert len(calls) == 2
    assert calls == ["tid001", "tid002"]
    # both outputs contain expected text
    assert (tmp_path / "c1.txt").read_text(encoding="utf-8") == "[A] hello"
    assert (tmp_path / "c2.txt").read_text(encoding="utf-8") == "[A] hello"


def test_nonexistent_file_exits_nonzero(monkeypatch, tmp_path, capsys):
    """Given nonexistent file, When transcribe, Then SystemExit nonzero with Chinese error and no traceback."""
    _patch_cli(monkeypatch)
    missing = str(tmp_path / "nope.wav")
    with pytest.raises(SystemExit) as exc:
        cli.main(["transcribe", missing])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "错误" in err
    assert "不存在" in err


def test_unsupported_extension_exits_nonzero(monkeypatch, tmp_path, capsys):
    """Given file with unsupported extension, When transcribe, Then SystemExit nonzero."""
    _patch_cli(monkeypatch)
    bad = tmp_path / "bad.xyz"
    bad.write_bytes(b"fake")

    with pytest.raises(SystemExit) as exc:
        cli.main(["transcribe", str(bad)])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "不支持的文件格式" in err


def test_out_with_single_file_via_namespace(monkeypatch, tmp_path, capsys):
    """Drive _cmd_transcribe directly via Namespace to pin import path variance."""
    calls, _ = _patch_cli(monkeypatch)
    wav = tmp_path / "d.wav"
    wav.write_bytes(b"RIFFfake")
    out_path = tmp_path / "custom_out.txt"

    ns = argparse.Namespace(audio=[str(wav)], format="txt", out=str(out_path))
    cli._cmd_transcribe(ns)

    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8") == "[A] hello"
    assert calls == ["tid001"]
