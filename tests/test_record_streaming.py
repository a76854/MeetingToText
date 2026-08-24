"""Focused regression tests for backend/app/routers/record.py WS streaming handler.

Audit coverage:
- task-6: B4 get_instance model-name mismatch; B5 unbounded audio_buffer after load failure
- task-7: same-path coverage for success replay/live partials, hard-cap enforcement,
  disabled-streaming short-circuit, and failure-state reset

FunASR is never imported or loaded here: StreamingASR.get_instance is fully
monkeypatched with fakes, and recorder_manager is replaced with an in-memory fake.
"""

import json
import logging
import threading
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.routers.record as record_module
import backend.app.services.record_session as record_session_module
from backend.app.config import settings


class FakeSession:
    def __init__(self):
        self.fed = []
        self.finalize_calls = 0

    def add_pcm_chunk(self, chunk):
        self.fed.append(chunk)
        return f"p{len(self.fed)}"

    def finalize(self):
        self.finalize_calls += 1
        return "final-partial"


class FakeInstance:
    def __init__(self, model_name, load_error=None, gate=None):
        self.model_name = model_name
        self.load_calls = 0
        self.load_error = load_error
        self.gate = gate
        self.session = None
        self.session_sample_rate = None
        self.load_finished = threading.Event()

    def load(self):
        try:
            self.load_calls += 1
            if self.gate is not None and not self.gate.wait(timeout=10):
                raise RuntimeError("test gate timeout")
            if self.load_error is not None:
                raise self.load_error
        finally:
            self.load_finished.set()

    def create_session(self, input_sample_rate):
        self.session_sample_rate = input_sample_rate
        self.session = FakeSession()
        return self.session


class FakeStreamingASR:
    calls = []
    instances = []
    load_error = None
    gate = None

    @classmethod
    def get_instance(cls, model_name="paraformer-zh-streaming", device="cpu"):
        cls.calls.append(model_name)
        inst = FakeInstance(model_name, load_error=cls.load_error, gate=cls.gate)
        cls.instances.append(inst)
        return inst


class FakeRecorderManager:
    def __init__(self, expected_chunks=0, release_gate=None):
        self.chunks = []
        self.sample_rates = []
        self.stopped = False
        self.expected_chunks = expected_chunks
        self.chunks_done = threading.Event()
        self.release_gate = release_gate

    def has_session(self, task_id):
        return False

    def get_session_state(self, task_id):
        return None

    def attach_owner(self, task_id, owner_id):
        return True

    def detach_owner(self, task_id, owner_id):
        pass

    async def start_recording(self, task_id):
        return f"/tmp/fake_{task_id}.wav"

    async def set_sample_rate(self, task_id, sample_rate):
        self.sample_rates.append(sample_rate)

    async def add_chunk(self, task_id, chunk):
        self.chunks.append(chunk)
        if self.expected_chunks and len(self.chunks) >= self.expected_chunks:
            self.chunks_done.set()
            if self.release_gate is not None:
                self.release_gate.set()

    async def stop_recording(self, task_id):
        self.stopped = True
        return None


class FailureLogHandler(logging.Handler):
    """Attached to record_module.logger; emit() runs synchronously inside
    record.py's except body on the event-loop thread, so error_seen doubles as
    an exact 'failure branch fully executed' barrier."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records = []
        self.error_seen = threading.Event()

    def emit(self, record):
        self.records.append(record)
        if record.levelno >= logging.ERROR and "load-failed" in record.getMessage():
            self.error_seen.set()


def _reset_fakes():
    FakeStreamingASR.calls = []
    FakeStreamingASR.instances = []
    FakeStreamingASR.load_error = None
    FakeStreamingASR.gate = None


def _wait_for_attempt(fake_asr, n, timeout=10):
    """Block until the n-th load attempt has started (get_instance called).
    get_instance runs inside the load task's first step, i.e. after a portal
    roundtrip — bare list indexing would race under load."""
    deadline = time.time() + timeout
    while len(fake_asr.instances) < n:
        if time.time() >= deadline:
            raise AssertionError(
                f"expected {n} load attempts, saw {len(fake_asr.instances)}"
            )
        time.sleep(0.01)
    return fake_asr.instances[n - 1]


@pytest.fixture()
def fake_asr(monkeypatch):
    _reset_fakes()
    monkeypatch.setattr(record_module, "StreamingASR", FakeStreamingASR)
    monkeypatch.setattr(settings, "streaming_asr_enabled", True)
    monkeypatch.setattr(settings, "streaming_asr_model_name", "custom-streaming-model")
    yield FakeStreamingASR
    if FakeStreamingASR.gate is not None:
        FakeStreamingASR.gate.set()
    _reset_fakes()


@pytest.fixture()
def ws_client(monkeypatch):
    def _make(recorder=None):
        rec = recorder or FakeRecorderManager()
        # stop_recording is called from the session service (finalize path),
        # the rest of the lifecycle from the router namespace.
        monkeypatch.setattr(record_module, "recorder_manager", rec)
        monkeypatch.setattr(record_session_module, "recorder_manager", rec)
        app = FastAPI()
        app.include_router(record_module.router)
        client = TestClient(app)
        return client, rec

    return _make


def _drain_until_status(ws):
    """Read messages until a terminal status frame; return all frames seen."""
    frames = []
    deadline = time.time() + 15
    while time.time() < deadline:
        msg = json.loads(ws.receive_text())
        frames.append(msg)
        if msg.get("status") in ("done", "error", "discarded"):
            return frames
    raise AssertionError("no terminal status frame within timeout")


def _read_partials(ws, count):
    partials = []
    deadline = time.time() + 15
    while len(partials) < count and time.time() < deadline:
        msg = json.loads(ws.receive_text())
        if msg.get("type") == "partial":
            partials.append(msg)
    assert len(partials) == count, f"expected {count} partials, got {len(partials)}"
    return partials


def test_b4_get_instance_uses_configured_model_name(fake_asr, ws_client):
    """B4: get_instance must be called once, with settings.streaming_asr_model_name."""
    client, rec = ws_client()
    with client.websocket_connect("/api/record/b4") as ws:
        ws.send_text(json.dumps({"type": "config", "sample_rate": 16000}))
        ws.send_bytes(b"\x01\x02" * 100)
        _read_partials(ws, 1)  # readiness observable: any fed chunk yields text
        ws.send_text(json.dumps({"action": "stop"}))
        _drain_until_status(ws)

    assert fake_asr.calls == ["custom-streaming-model"]
    inst = fake_asr.instances[0]
    assert inst.model_name == "custom-streaming-model"
    assert inst.load_calls == 1
    assert inst.session_sample_rate == 16000
    assert len(inst.session.fed) >= 1  # chunk reached the model (replay or live)
    assert rec.stopped is True


def test_b5_load_failure_resets_state_and_logs(fake_asr, ws_client):
    """B5: on load failure -> log load-failed, reset model_loading so a later
    config can retry, keep streaming not-ready (no partials, no finalize)."""
    fake_asr.load_error = RuntimeError("boom")
    log_capture = FailureLogHandler()
    record_module.logger.addHandler(log_capture)
    try:
        client, rec = ws_client()
        with client.websocket_connect("/api/record/b5") as ws:
            ws.send_text(json.dumps({"type": "config", "sample_rate": 16000}))
            inst1 = _wait_for_attempt(fake_asr, 1)
            assert inst1.load_finished.wait(10)

            # error_seen proves record.py's failure branch (which resets
            # model_loading) fully ran, so the retry below cannot be guard-dropped.
            assert log_capture.error_seen.wait(10)
            ws.send_text(json.dumps({"type": "config", "sample_rate": 16000}))
            inst2 = _wait_for_attempt(fake_asr, 2)
            assert inst2.load_finished.wait(10)

            ws.send_bytes(b"\x00\x00" * 16)  # post-failure chunk: must be ignored, not buffered forever
            ws.send_text(json.dumps({"action": "stop"}))
            frames = _drain_until_status(ws)
    finally:
        record_module.logger.removeHandler(log_capture)

    assert fake_asr.calls == ["custom-streaming-model"] * 2
    assert all(i.session is None for i in fake_asr.instances)
    assert all(m.get("type") != "partial" for m in frames)
    errors = [r for r in log_capture.records if r.levelno >= logging.ERROR]
    assert any("load-failed" in r.getMessage() for r in errors)


def test_b5_audio_buffer_hard_cap_under_gated_load(fake_asr, ws_client):
    """B5 defense-in-depth: while load is blocked, buffered audio is capped at
    ~10s (sample_rate*2*AUDIO_BUFFER_MAX_SECONDS); oldest chunks are dropped."""
    sample_rate = 8000
    cap_bytes = sample_rate * 2 * record_module.AUDIO_BUFFER_MAX_SECONDS  # 160000
    chunk = b"\x00\x01" * 15000  # 30000 bytes
    n_chunks = 8  # 240000 bytes total -> trimming must drop the first 3 chunks
    gate = threading.Event()
    fake_asr.gate = gate
    # Recorder releases the gate from the loop thread once all chunks are
    # consumed, so the handler's final append+trim is ordered before replay.
    rec = FakeRecorderManager(expected_chunks=n_chunks, release_gate=gate)
    client, _ = ws_client(rec)

    sent = []
    with client.websocket_connect("/api/record/cap") as ws:
        ws.send_text(json.dumps({"type": "config", "sample_rate": sample_rate}))
        for _ in range(n_chunks):
            sent.append(chunk)
            ws.send_bytes(chunk)
        assert rec.chunks_done.wait(10)  # all chunks consumed into (trimmed) buffer

        _read_partials(ws, 5)  # one partial per replayed chunk => replay finished
        ws.send_text(json.dumps({"action": "stop"}))
        _drain_until_status(ws)

    inst = fake_asr.instances[0]
    fed = inst.session.fed
    assert sum(len(c) for c in fed) <= cap_bytes
    assert sum(len(c) for c in fed) < sum(len(c) for c in sent)  # drops happened
    assert fed == sent[3:]  # deterministic drop-oldest outcome


def test_streaming_disabled_never_loads_model(monkeypatch, ws_client, fake_asr):
    """task-7 coverage: streaming disabled -> zero get_instance calls, clean stop."""
    monkeypatch.setattr(settings, "streaming_asr_enabled", False)
    client, rec = ws_client()
    with client.websocket_connect("/api/record/off") as ws:
        ws.send_text(json.dumps({"type": "config", "sample_rate": 16000}))
        ws.send_bytes(b"\x00\x00" * 16)
        ws.send_text(json.dumps({"action": "stop"}))
        _drain_until_status(ws)

    assert fake_asr.calls == []
    assert rec.stopped is True
