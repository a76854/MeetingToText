"""Router-level tests for backend/app/routers/transcribe.py and generate.py.

Both routers were previously zero-covered. A minimal FastAPI app mounts ONLY
these two routers (never backend.app.server — no lifespan, no preload, no
SPA fallback), and every async seam is controlled:

- ``transcribe_module.get_task`` / ``generate_module.get_task``: patched to
  scripted TaskInfo states (SSE progression) or None (404 pins). The router
  imports these by name, so the patch must land in the ROUTER module
  namespace (same pattern as tests/test_reconnect_ws.py PipelineSpy).
- ``transcribe_module.submit_pipeline``: patched to a recorder — no real
  pipeline is ever submitted to the pipeline thread pool.
- ``generate_module.get_llm``: patched with a fake whose ``api_key`` and
  ``generate()`` drive the guard rails; no network, no openai client.
- ``settings.data_dir`` is redirected to tmp_path and the TaskStore singleton
  is reset, so persistence assertions (save_minutes / update_segments) hit a
  fresh per-test SQLite db (fixture pattern from tests/test_reconnect_ws.py:68-84).

Deliberate pins — the CURRENT mixed EN/ZH detail strings, scheduled for
normalization later; these tests are the safety net. Pin them VERBATIM:
  "Task not found"               transcribe.py:24/:35/:53, generate.py:29
  "任务正在转录中"                 transcribe.py:26/:38
  "音频文件不存在，无法重新转录"      transcribe.py:37
  "只有已完成的任务才能编辑"         transcribe.py:104
  "No transcript available"      generate.py:31
  "Unknown template: ..."        generate.py:35
  "请先在设置中配置 LLM API Key"    generate.py:49
  "LLM 调用失败: ..."             generate.py:60

Also pinned:
- full_text rebuild separator at transcribe.py:107 is "\\n\\n" (the TXT
  export side uses a single "\\n" and is pinned by tests/golden/test_export.py).
- SSE wire shape: transcribe.py:53/:71 use json.dumps(..., ensure_ascii=False)
  → human-readable separators (", " and ": "); transcribe.py:66/:74 use
  model_dump_json() → compact separators. The two shapes differ and are
  asserted EXACTLY on the raw frames below.
- generate.py used to dual-write minutes (in-memory task.minutes plus
  store.save_minutes); todo 10 collapsed that into the single store path.
  We still pin the OBSERVABLE contract: store receives the minutes exactly
  once and the response echoes the text.

# PROMPT-ASSERTIONS-PORTED-BY-TODO-10 (LANDED)
# The string assertions listed below were deliberately deferred while the
# message-builder module did not exist; todo 10 created it and ported them
# into its own unit test module (tests/test_prompts.py):
#   - system PROMPT assembly (generate.py:37-40): template system_prompt plus
#     the output_format suffix injection
#   - user-message scaffold (generate.py:42-45): the "=== 会议转录开始 ===" fence
#     and the custom_instructions appendix
# One seam-level string assertion was added to the happy path below as well.
# Our generate fakes additionally record the kwarg KEYS (temperature /
# max_tokens) so the passthrough stays pinned at the router seam.
"""

import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.routers.generate as generate_module
import backend.app.routers.transcribe as transcribe_module
import backend.app.services.store as store_module
from backend.app.config import settings
from backend.app.models.schemas import (
    ProgressInfo,
    StepInfo,
    TaskInfo,
    TaskResult,
    TaskStatus,
    TranscriptSegment,
)
from backend.app.services.store import get_store


def _new_task_id() -> str:
    return f"tg_{uuid4().hex[:10]}"


def _make_task(**kwargs) -> TaskInfo:
    """Build a TaskInfo with sensible defaults; override via kwargs."""
    defaults = dict(
        id=_new_task_id(),
        status=TaskStatus.done,
        filename="meeting.wav",
        audio_path="/audio/meeting.wav",
        result=TaskResult(segments=[], full_text="会议内容", duration=1.0),
        error=None,
    )
    defaults.update(kwargs)
    return TaskInfo(**defaults)


def _seed_task(store, *, status=TaskStatus.done, full_text="会议内容", error=None):
    """Persist a task row; create() drops result/status details, so re-apply them."""
    task = _make_task(status=status, full_text=full_text, error=error)
    store.create(task)
    if full_text:
        # save_result stamps status=done; re-stamp below if a non-done status
        # is requested so the seeded status is exactly what the test wants.
        store.save_result(task.id, TaskResult(segments=[], full_text=full_text, duration=1.0))
    store.update_progress(task.id, status, error)
    return store.get(task.id)


def _parse_sse(body: str) -> list[dict]:
    """Parse the raw SSE wire text into [{"event": ..., "data": ...}] frames.

    Parses the REAL serialized stream (not any mocked emitter return value),
    so the exact frame names and payload bytes pin the generator's wire shape.
    Lines starting with ":" (keep-alive comments) are ignored.
    """
    frames = []
    cur_event: str | None = None
    cur_data: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line == "":
            if cur_event is not None:
                frames.append({"event": cur_event, "data": "\n".join(cur_data)})
            cur_event, cur_data = None, []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            cur_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            cur_data.append(line[len("data:"):].strip())
    if cur_event is not None:
        frames.append({"event": cur_event, "data": "\n".join(cur_data)})
    return frames


# ------------------------------------------------------------------ fixtures


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """Redirect settings to tmp_path and reset the TaskStore singleton.

    db_path / temp_dir / upload_dir are read-only properties over data_dir
    (config.py:66-80), so redirecting data_dir redirects all three.
    """
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    os.makedirs(settings.temp_dir, exist_ok=True)
    os.makedirs(settings.upload_dir, exist_ok=True)
    store_module._store = None  # force re-init against the tmp db (store.py:215-225)
    yield get_store()
    store_module._store = None  # never leak a tmp-db singleton to other tests


@pytest.fixture()
def client(env):
    """Minimal app mounting ONLY the two routers under test."""
    app = FastAPI()
    app.include_router(transcribe_module.router)
    app.include_router(generate_module.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def submit_spy(monkeypatch):
    """Replace submit_pipeline with a recorder; no real pipeline ever runs."""
    calls: list[str] = []
    monkeypatch.setattr(transcribe_module, "submit_pipeline", lambda tid: calls.append(tid))
    return calls


# ------------------------------------------------------------- transcribe


@pytest.mark.parametrize(
    "endpoint",
    ["/api/transcribe/{tid}", "/api/transcribe/{tid}/retry"],
    ids=["start", "retry"],
)
def test_transcribe_nonexistent_task_404(client, submit_spy, monkeypatch, endpoint):
    monkeypatch.setattr(transcribe_module, "get_task", lambda tid: None)
    resp = client.post(endpoint.format(tid="nope"))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Task not found"}
    assert submit_spy == []


def test_transcribe_while_processing_400(client, submit_spy, monkeypatch):
    monkeypatch.setattr(
        transcribe_module,
        "get_task",
        lambda tid: _make_task(status=TaskStatus.processing, result=None),
    )
    resp = client.post("/api/transcribe/task_busy")
    assert resp.status_code == 400
    assert resp.json() == {"detail": "任务正在转录中"}
    assert submit_spy == []


def test_retry_transcribe_missing_audio_400(client, submit_spy, monkeypatch):
    monkeypatch.setattr(
        transcribe_module,
        "get_task",
        lambda tid: _make_task(status=TaskStatus.error, audio_path="", result=None),
    )
    resp = client.post("/api/transcribe/task_noaudio/retry")
    assert resp.status_code == 400
    assert resp.json() == {"detail": "音频文件不存在，无法重新转录"}
    assert submit_spy == []


def test_retry_transcribe_success_resets_and_submits(env, client, submit_spy, monkeypatch, tmp_path):
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"\x00\x01")
    monkeypatch.setattr(
        transcribe_module,
        "get_task",
        lambda tid: _make_task(status=TaskStatus.error, audio_path=str(audio), result=None),
    )
    resp = client.post("/api/transcribe/task_retry/retry")
    assert resp.status_code == 200
    assert resp.json() == {"status": "restarted", "task_id": "task_retry"}
    assert submit_spy == ["task_retry"]


def test_stream_emits_progress_then_done(client, monkeypatch):
    """Real SSE frames from the wire: progress, progress, done — then stream ends."""
    done_task = _make_task(
        status=TaskStatus.done,
        progress=ProgressInfo(
            current_step="asr",
            overall=1.0,
            steps=[StepInfo(name="vad", status="done"), StepInfo(name="asr", status="done")],
        ),
    )
    states = [
        _make_task(
            status=TaskStatus.pending,
            progress=ProgressInfo(current_step="vad", overall=0.0,
                                  steps=[StepInfo(name="vad", status="pending")]),
            result=None,
        ),
        _make_task(
            status=TaskStatus.processing,
            progress=ProgressInfo(current_step="asr", overall=0.35,
                                  steps=[StepInfo(name="vad", status="done"),
                                         StepInfo(name="asr", status="running")]),
            result=None,
        ),
        done_task,
    ]
    seen: list[str] = []

    def fake_get_task(tid):
        seen.append(tid)
        return states.pop(0) if states else done_task

    monkeypatch.setattr(transcribe_module, "get_task", fake_get_task)
    resp = client.get("/api/transcribe/task_stream/stream")
    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    assert [f["event"] for f in frames] == ["progress", "progress", "done"]
    assert all(tid == "task_stream" for tid in seen)

    # progress frames carry compact model_dump_json (transcribe.py:66/:74)
    p0 = json.loads(frames[0]["data"])
    assert p0["status"] == "pending"
    assert p0["progress"]["current_step"] == "vad"
    p1 = json.loads(frames[1]["data"])
    assert p1["status"] == "processing"

    # done frame is EXACTLY task.model_dump_json() — compact separators.
    assert frames[2]["data"] == done_task.model_dump_json()
    assert '"id":"' in frames[2]["data"]


def test_stream_error_event_shape(client, monkeypatch):
    """error state → single error frame; json.dumps shape (spaces, raw Chinese)."""
    failed = _make_task(status=TaskStatus.error, error="识别失败", result=None)
    monkeypatch.setattr(transcribe_module, "get_task", lambda tid: failed)
    resp = client.get("/api/transcribe/task_fail/stream")
    frames = _parse_sse(resp.text)
    assert frames == [{"event": "error", "data": '{"error": "识别失败"}'}]


def test_stream_missing_task_error_frame(client, monkeypatch):
    monkeypatch.setattr(transcribe_module, "get_task", lambda tid: None)
    resp = client.get("/api/transcribe/task_ghost/stream")
    frames = _parse_sse(resp.text)
    assert frames == [{"event": "error", "data": '{"error": "Task not found"}'}]


def test_update_transcript_nonexistent_404(env, client):
    resp = client.put(
        "/api/transcript/task_ghost",
        json={"segments": [{"start": 0.0, "end": 1.0, "speaker": "甲", "text": "你好"}]},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Task not found"}


def test_update_transcript_rejects_non_done_400(env, client):
    task = _seed_task(env, status=TaskStatus.pending, full_text="")
    resp = client.put(
        f"/api/transcript/{task.id}",
        json={"segments": [{"start": 0.0, "end": 1.0, "speaker": "甲", "text": "你好"}]},
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "只有已完成的任务才能编辑"}


def test_update_transcript_done_rebuilds_full_text(env, client):
    """Pin the "\\n\\n" rebuild separator at transcribe.py:107 (TXT export uses "\\n")."""
    task = _seed_task(env, status=TaskStatus.done, full_text="old text")
    segments = [
        {"start": 0.0, "end": 1.5, "speaker": "甲", "text": "你好"},
        {"start": 1.5, "end": 3.0, "speaker": "乙", "text": "大家好"},
    ]
    resp = client.put(f"/api/transcript/{task.id}", json={"segments": segments})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "task_id": task.id, "segment_count": 2}

    stored = env.get(task.id)
    assert stored.result.full_text == "[甲] 你好\n\n[乙] 大家好"
    assert [s.text for s in stored.result.segments] == ["你好", "大家好"]


# --------------------------------------------------------------- generate


class _FakeLLM:
    def __init__(self, api_key="sk-fake", reply="纪要文本"):
        self.api_key = api_key
        self.reply = reply
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _seed_done_with_text(store):
    return _seed_task(store, status=TaskStatus.done, full_text="真实会议转录文本")


def test_generate_nonexistent_task_404(env, client):
    resp = client.post("/api/generate", json={"task_id": "task_ghost"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Task not found"}


def test_generate_no_transcript_400(env, client):
    task = _seed_task(env, status=TaskStatus.done, full_text="")  # result is None
    assert task.result is None
    resp = client.post("/api/generate", json={"task_id": task.id})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "No transcript available"}


def test_generate_unknown_template_400(env, client):
    task = _seed_done_with_text(env)
    resp = client.post(
        "/api/generate", json={"task_id": task.id, "template_id": "does_not_exist"}
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Unknown template: does_not_exist"}


def test_generate_missing_llm_key_400(env, client, monkeypatch):
    task = _seed_done_with_text(env)
    fake = _FakeLLM(api_key="")
    monkeypatch.setattr(generate_module, "get_llm", lambda: fake)
    resp = client.post("/api/generate", json={"task_id": task.id})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "请先在设置中配置 LLM API Key"}
    assert fake.calls == []
    assert env.get(task.id).minutes is None


def test_generate_llm_error_500_and_no_persist(env, client, monkeypatch):
    task = _seed_done_with_text(env)
    fake = _FakeLLM(reply=RuntimeError("boom"))
    monkeypatch.setattr(generate_module, "get_llm", lambda: fake)
    resp = client.post("/api/generate", json={"task_id": task.id})
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail.startswith("LLM 调用失败") and "boom" in detail
    # Failure path must not half-persist anything.
    assert env.get(task.id).minutes is None
    assert len(fake.calls) == 1


def test_generate_success_echoes_and_persists_once(env, client, monkeypatch):
    """Happy path: response echoes text; store receives save_minutes EXACTLY once.

    The former dual-write (in-memory + store) was collapsed by todo 10;
    the observable contract pinned here — one store write, one echo — is
    the single-write behavior that must survive.
    """
    task = _seed_done_with_text(env)
    fake = _FakeLLM(reply="## 会议纪要\n\n决定事项…")
    monkeypatch.setattr(generate_module, "get_llm", lambda: fake)

    save_calls: list[tuple[str, str]] = []
    original_save = env.save_minutes

    def spy_save_minutes(tid, minutes):
        save_calls.append((tid, minutes))
        original_save(tid, minutes)

    monkeypatch.setattr(env, "save_minutes", spy_save_minutes)

    resp = client.post("/api/generate", json={"task_id": task.id})
    assert resp.status_code == 200
    assert resp.json() == {"minutes": "## 会议纪要\n\n决定事项…"}
    assert save_calls == [(task.id, "## 会议纪要\n\n决定事项…")]
    assert env.get(task.id).minutes == "## 会议纪要\n\n决定事项…"
    # Kwarg KEYS pin the passthrough; string contents are additionally pinned
    # at the seam below (full byte parity lives in the builder's unit tests).
    assert set(fake.calls[0]) == {"system_prompt", "user_message", "temperature", "max_tokens"}
    assert fake.calls[0]["user_message"].endswith(
        "=== 会议转录开始 ===\n真实会议转录文本\n=== 会议转录结束 ==="
    )


def test_update_minutes_persists(env, client):
    task = _seed_done_with_text(env)
    resp = client.put(f"/api/minutes/{task.id}", json={"minutes": "修订后的纪要"})
    assert resp.status_code == 200
    assert resp.json() == {"minutes": "修订后的纪要"}
    assert env.get(task.id).minutes == "修订后的纪要"
