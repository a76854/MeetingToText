"""WS-level reconnect-resume scenario tests (task 27, Metis C5).

End-to-end through the real /api/record/{task_id} websocket handler
(record_websocket) via TestClient.websocket_connect — complements the
recorder_manager-level unit tests in test_reconnect_backend.py.

Hermetic: no FunASR anywhere.
- pipeline side effects faked in the record_session_module namespace
  (create_task / submit_pipeline) so "task created" is observable without a
  DB or ASR (todo 12 moved those calls from record.py into the session
  service; the patch target followed).
- streaming ASR faked by replacing record_module.StreamingASR wholesale
  (task-6 learning: patch module globals imported by name).
- audio lands under a tmp data_dir (settings.data_dir redirect; temp_dir /
  upload_dir are read-only properties over it — task-9 learning).

Determinism rules (task-6-fix learnings):
- bounded polls for any server-side state mutated on the event loop, never
  bare indexing right after send;
- protocol barriers preferred where the server message order guarantees them
  ({"status":"resumed"} is sent AFTER attach_owner succeeds);
- log-message barrier ("streaming ASR ready") before feeding chunks in the
  streaming test — emit() runs synchronously inside logger.info ON THE LOOP
  THREAD after streaming_ready=True and buffer replay finished;
- malformed JSON text frames get {"status":"error","message":"invalid json"}
  and the session stays alive (todo 13 fix: previously such a frame fell into
  the handler's outer catch-all and silently suspended the recording);
- grace=1 (not 0) for the expiry test: liveness timeout = 3×grace with a
  0.05s floor, so grace=0 would liveness-suspend the ACTIVE connection
  between frames and flake. 1s keeps expiry fast AND the live connection safe.
"""

import os
import json
import uuid
import wave
import time
import logging
import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.routers.record as record_module
import backend.app.services.record_session as record_session_module
from backend.app.services.record_session import record_session_service
from backend.app.config import settings
from backend.app.services.recorder import (
    STATE_ACTIVE,
    STATE_SUSPENDED,
    recorder_manager,
)


def _new_task_id():
    return f"wsreconn_{uuid.uuid4().hex[:8]}"


def _poll(predicate, timeout=5.0, interval=0.01):
    """Bounded wait for server-loop-mutated state; never bare-index after send."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ---------------------------------------------------------------- fixtures


@pytest.fixture()
def ws_client(monkeypatch, tmp_path):
    """Minimal app (no lifespan/preload) + tmp data dir so no real data/ writes."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    # config.py makedirs these at import time against the REAL data_dir; the
    # redirect needs its own copies or wave.open() raises inside the WS loop,
    # where record.py's outer handler logs it (logger.exception) before
    # suspending — silently swallowed by `except Exception: pass` before todo 13.
    os.makedirs(settings.temp_dir, exist_ok=True)
    os.makedirs(settings.upload_dir, exist_ok=True)
    app = FastAPI()
    app.include_router(record_module.router)
    # Context-managed => ONE shared portal/event-loop for every WS session and
    # HTTP call in the test. With per-session portals (plain TestClient), each
    # `with ws:` exit kills that session's loop — silently cancelling any
    # grace-expiry timer the handler armed, so expiry could never fire.
    with TestClient(app) as client:
        yield client


class PipelineSpy:
    def __init__(self):
        self.created = []
        self.submitted = []

    def install(self, monkeypatch):
        def fake_create_task(filename, audio_path):
            self.created.append({"filename": filename, "audio_path": audio_path})
            return SimpleNamespace(id=f"pipe_{len(self.created)}")

        monkeypatch.setattr(record_session_module, "create_task", fake_create_task)
        monkeypatch.setattr(
            record_session_module, "submit_pipeline", lambda tid: self.submitted.append(tid)
        )
        return self


@pytest.fixture()
def pipeline_spy(monkeypatch):
    return PipelineSpy().install(monkeypatch)


@pytest.fixture(autouse=True)
def _no_leaked_sessions_or_timers():
    """Snapshot-and-clean: cancel grace timers + discard sessions this test made."""
    pre_sessions = set(recorder_manager._active_recordings)
    pre_timers = set(record_session_service._grace_timers)
    yield
    for tid, timer in list(record_session_service._grace_timers.items()):
        if tid not in pre_timers:
            timer.cancel()
            record_session_service._grace_timers.pop(tid, None)
    leftovers = [
        tid
        for tid in recorder_manager._active_recordings
        if tid not in pre_sessions
    ]
    if leftovers:
        async def _discard_all():
            for tid in leftovers:
                await recorder_manager.discard_recording(tid)

        asyncio.run(_discard_all())


def _connect(client, task_id):
    return client.websocket_connect(f"/api/record/{task_id}")


def _config(ws, sample_rate=16000):
    ws.send_json({"type": "config", "sample_rate": sample_rate})


def _wav_frames(path):
    with wave.open(path, "rb") as wf:
        return wf.getframerate(), wf.readframes(wf.getnframes())


# ------------------------------------------------------- scenario 1: suspend


def test_01_abrupt_close_suspends_session_without_task(pipeline_spy, ws_client):
    """Connect → config → chunks → abrupt close (no stop/discard):
    session survives as suspended, grace timer armed, ZERO tasks created."""
    tid = _new_task_id()
    with _connect(ws_client, tid) as ws:
        _config(ws)
        ws.send_bytes(b"\x01\x00" * 100)
        ws.send_bytes(b"\x02\x00" * 50)
    # context exit == abrupt client drop; handler notices via WebSocketDisconnect

    assert _poll(lambda: recorder_manager.get_session_state(tid) == STATE_SUSPENDED), (
        "session was not suspended after abrupt close"
    )
    assert recorder_manager.has_session(tid)
    assert tid in record_session_service._grace_timers, "grace finalize was not armed"
    assert pipeline_spy.created == [], "a task was created during suspend"
    assert pipeline_spy.submitted == []


# --------------------------------------------------------- scenario 2: resume


def test_02_reconnect_resumes_same_wav_and_stops_into_one_task(pipeline_spy, ws_client):
    """Reconnect SAME task_id during grace → {'status':'resumed'} → more chunks
    → stop: exactly ONE task whose wav holds BOTH connections' bytes."""
    tid = _new_task_id()
    first = b"\x11\x00" * 400
    second = b"\x22\x00" * 300

    with _connect(ws_client, tid) as ws:
        _config(ws)
        ws.send_bytes(first)
    assert _poll(lambda: recorder_manager.get_session_state(tid) == STATE_SUSPENDED)

    # reconnect inside the grace window
    with _connect(ws_client, tid) as ws:
        # protocol barrier: 'resumed' is sent only after resume+attach_owner won
        assert ws.receive_json() == {"status": "resumed"}
        _config(ws)  # client re-sends config after reconnect; idempotent server-side
        ws.send_bytes(second)
        ws.send_json({"action": "stop"})
        done = ws.receive_json()

    assert done["status"] == "done"
    assert done["task_id"] == "pipe_1"
    assert len(pipeline_spy.created) == 1
    assert pipeline_spy.submitted == ["pipe_1"]
    dest = pipeline_spy.created[0]["audio_path"]
    framerate, frames = _wav_frames(dest)
    assert framerate == 16000
    assert frames == first + second, "wav must contain both connections' chunks"
    os.remove(dest)
    assert not recorder_manager.has_session(tid)
    assert tid not in record_session_service._grace_timers, "adoption must cancel the timer"


# ------------------------------------------------------- scenario 3: supersede


def test_03_second_ws_while_active_gets_busy_1008_first_unaffected(pipeline_spy, ws_client):
    """Hold first WS active, open second WS same task_id: second gets
    session_busy error + close 1008; first session keeps working."""
    tid = _new_task_id()
    first = b"\x0a\x00" * 64
    extra = b"\x0e\x00" * 32

    with _connect(ws_client, tid) as primary:
        _config(primary)
        primary.send_bytes(first)
        # owner binding happens right after accept; poll instead of assuming
        assert _poll(
            lambda: recorder_manager._active_recordings[tid]["owner"] is not None
        )

        # __enter__ creates the session's portal + performs the connect
        # handshake; receive() before that fails with no attribute 'portal'.
        with ws_client.websocket_connect(f"/api/record/{tid}") as second:
            msg = second.receive()  # raw ASGI message dict
            assert msg["type"] == "websocket.send"
            err = json.loads(msg["text"])
            assert err["status"] == "error"
            assert err["code"] == "session_busy"
            close_msg = second.receive()
            assert close_msg["type"] == "websocket.close"
            assert close_msg["code"] == 1008

        # first session unaffected: still ACTIVE and accepts more audio
        assert recorder_manager.get_session_state(tid) == STATE_ACTIVE
        primary.send_bytes(extra)
        primary.send_json({"action": "stop"})
        done = primary.receive_json()

    assert done["status"] == "done"
    assert len(pipeline_spy.created) == 1
    _, frames = _wav_frames(pipeline_spy.created[0]["audio_path"])
    assert frames == first + extra
    os.remove(pipeline_spy.created[0]["audio_path"])


# --------------------------------------------------------- scenario 4: expiry


def test_04_grace_expiry_auto_finalizes_exactly_one_task(pipeline_spy, ws_client, monkeypatch):
    """Suspend with tiny grace → no reconnect → server auto-finalizes the wav
    into exactly ONE pipeline task."""
    # tiny-but-nonzero: see module docstring (liveness floor vs grace=0 flake)
    monkeypatch.setattr(settings, "reconnect_grace_seconds", 1)
    tid = _new_task_id()
    chunk = b"\x33\x00" * 200

    with _connect(ws_client, tid) as ws:
        _config(ws)
        ws.send_bytes(chunk)
    assert _poll(lambda: recorder_manager.get_session_state(tid) == STATE_SUSPENDED)

    assert _poll(lambda: len(pipeline_spy.created) == 1, timeout=6.0), (
        "grace-expiry did not auto-finalize into a task"
    )
    assert pipeline_spy.submitted == ["pipe_1"]
    assert not recorder_manager.has_session(tid)
    assert tid not in record_session_service._grace_timers
    _, frames = _wav_frames(pipeline_spy.created[0]["audio_path"])
    assert frames == chunk
    os.remove(pipeline_spy.created[0]["audio_path"])


# ------------------------------------------- scenario 5: discard while suspended


def test_05_delete_discards_suspended_session_zero_tasks(pipeline_spy, ws_client):
    """Suspended session + DELETE /api/record/{id}: file gone, zero tasks,
    grace timer cancelled, repeat DELETE 404s."""
    tid = _new_task_id()
    with _connect(ws_client, tid) as ws:
        _config(ws)
        ws.send_bytes(b"\x44\x00" * 128)
    assert _poll(lambda: recorder_manager.get_session_state(tid) == STATE_SUSPENDED)
    filepath = recorder_manager._active_recordings[tid]["filepath"]
    assert os.path.exists(filepath)

    resp = ws_client.delete(f"/api/record/{tid}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert not os.path.exists(filepath)
    assert not recorder_manager.has_session(tid)
    assert tid not in record_session_service._grace_timers, "DELETE must cancel the timer"
    assert pipeline_spy.created == []
    assert ws_client.delete(f"/api/record/{tid}").status_code == 404


# ------------------------------------------------- scenario 6: stop immediately


class _FakeStreamingSession:
    def __init__(self):
        self.chunks = []
        self.finalize_calls = 0

    def add_pcm_chunk(self, chunk):
        self.chunks.append(chunk)
        return None  # no mid-stream partials needed

    def finalize(self):
        self.finalize_calls += 1
        return f"final:{len(self.chunks)}"


class FakeStreamingASR:
    """Replaces record_module.StreamingASR wholesale (no real model)."""

    instances = []

    def __init__(self, model_name):
        self.model_name = model_name
        self.session = None
        FakeStreamingASR.instances.append(self)

    @classmethod
    def get_instance(cls, model_name):
        for inst in cls.instances:
            if inst.model_name == model_name:
                return inst
        return cls(model_name)

    def load(self):
        pass  # instant fake load

    def create_session(self, sample_rate):
        self.session = _FakeStreamingSession()
        return self.session


def test_06_stop_immediately_finalizes_streaming_into_one_task(pipeline_spy, ws_client, monkeypatch):
    """config→chunks→stop with streaming enabled: final partial delivered
    (finalize-fix proof), exactly one task, no grace wait/timer."""
    monkeypatch.setattr(settings, "streaming_asr_enabled", True)
    FakeStreamingASR.instances.clear()
    monkeypatch.setattr(record_module, "StreamingASR", FakeStreamingASR)

    # Barrier: record.py logs "streaming ASR ready" AFTER streaming_ready=True
    # and buffer replay finished — emit runs on the loop thread (task-6-fix).
    ready = threading.Event()

    class _ReadyHandler(logging.Handler):
        def emit(self, record):
            if "streaming ASR ready" in record.getMessage():
                ready.set()

    handler = _ReadyHandler(level=logging.INFO)
    # pytest's root logger sits at WARNING, which gates isEnabledFor(INFO)
    # BEFORE handlers run — raise this logger's level or the barrier never
    # fires. Restored in finally.
    old_level = record_module.logger.level
    record_module.logger.setLevel(logging.INFO)
    record_module.logger.addHandler(handler)
    try:
        tid = _new_task_id()
        chunk_a = b"\x55\x00" * 40
        chunk_b = b"\x66\x00" * 60
        with _connect(ws_client, tid) as ws:
            _config(ws)
            assert ready.wait(5.0), "fake streaming ASR never became ready"
            ws.send_bytes(chunk_a)
            ws.send_bytes(chunk_b)
            ws.send_json({"action": "stop"})
            final_partial = ws.receive_json()
            done = ws.receive_json()
    finally:
        record_module.logger.removeHandler(handler)
        record_module.logger.setLevel(old_level)

    assert final_partial == {"type": "partial", "text": "final:2", "final": True}
    assert done["status"] == "done" and done["task_id"] == "pipe_1"

    assert len(FakeStreamingASR.instances) == 1
    sess = FakeStreamingASR.instances[0].session
    assert sess.chunks == [chunk_a, chunk_b], "chunks must reach the live stream path"
    assert sess.finalize_calls == 1, "finalize must run exactly once on stop"
    assert len(pipeline_spy.created) == 1
    assert pipeline_spy.submitted == ["pipe_1"]
    assert not recorder_manager.has_session(tid)
    assert tid not in record_session_service._grace_timers, "explicit stop arms no timer"
    os.remove(pipeline_spy.created[0]["audio_path"])


# ------------------------------------------------- scenario 7: malformed json


def test_malformed_json_gets_error_frame(pipeline_spy, ws_client):
    """A non-JSON text frame must yield {"status":"error","message":"invalid json"}
    and leave the session ALIVE: before todo 13 such a frame hit the handler's
    outer catch-all and silently suspended the recording."""
    tid = _new_task_id()
    with _connect(ws_client, tid) as ws:
        _config(ws)
        ws.send_bytes(b"\x77\x00" * 100)
        ws.send_text("not-json{{{")
        err = ws.receive_json()
        assert err == {"status": "error", "message": "invalid json"}

        # Only the bad frame was skipped: later audio is still accepted and a
        # clean stop still finalizes into exactly one task.
        ws.send_bytes(b"\x88\x00" * 50)
        assert _poll(lambda: recorder_manager.get_session_state(tid) == STATE_ACTIVE)
        ws.send_json({"action": "stop"})
        done = ws.receive_json()

    assert done["status"] == "done"
    assert done["task_id"] == "pipe_1"
    assert len(pipeline_spy.created) == 1
    os.remove(pipeline_spy.created[0]["audio_path"])
