"""Backend unit tests for reconnect-resume (tasks 23/24).

Covers the RecorderManager state machine (active <-> suspended, single-owner
guard, discard) and record.py's grace-expiry finalize + DELETE route.

No FunASR anywhere: only recorder.py state plus monkeypatched
create_task/submit_pipeline in the record module namespace.
"""

import os
import uuid
import wave
import asyncio
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
    return f"reconn_{uuid.uuid4().hex[:8]}"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_pending_grace_timers():
    yield
    for timer in list(record_session_service._grace_timers.values()):
        timer.cancel()
    record_session_service._grace_timers.clear()


def test_suspend_resume_roundtrip_transitions_state_and_owner():
    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    assert recorder_manager.get_session_state(task_id) == STATE_ACTIVE

    assert recorder_manager.attach_owner(task_id, "conn-a") is True

    assert _run(recorder_manager.suspend_recording(task_id)) is True
    assert recorder_manager.get_session_state(task_id) == STATE_SUSPENDED

    assert _run(recorder_manager.resume_recording(task_id, "conn-b")) is True
    assert recorder_manager.get_session_state(task_id) == STATE_ACTIVE


def test_suspend_rejects_missing_or_already_suspended():
    assert _run(recorder_manager.suspend_recording(_new_task_id())) is False

    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    assert _run(recorder_manager.suspend_recording(task_id)) is True
    assert _run(recorder_manager.suspend_recording(task_id)) is False
    _run(recorder_manager.discard_recording(task_id))


def test_resume_rejects_active_or_missing_session():
    assert _run(recorder_manager.resume_recording(_new_task_id(), "c")) is False

    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    assert _run(recorder_manager.resume_recording(task_id, "c")) is False
    _run(recorder_manager.discard_recording(task_id))


def test_second_concurrent_owner_is_superseded_rejected_then_adopts_after_suspend():
    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    assert recorder_manager.attach_owner(task_id, "conn-a") is True
    assert recorder_manager.attach_owner(task_id, "conn-b") is False

    _run(recorder_manager.suspend_recording(task_id))
    assert recorder_manager.attach_owner(task_id, "conn-b") is True
    assert recorder_manager.attach_owner(task_id, "conn-a") is False
    _run(recorder_manager.discard_recording(task_id))


def test_discard_deletes_file_from_any_state_and_creates_nothing():
    for setup in ("active", "suspended"):
        task_id = _new_task_id()
        _run(recorder_manager.start_recording(task_id))
        _run(recorder_manager.set_sample_rate(task_id, 16000))
        _run(recorder_manager.add_chunk(task_id, b"\x00\x00" * 64))
        filepath = recorder_manager._active_recordings[task_id]["filepath"]
        assert os.path.exists(filepath)

        if setup == "suspended":
            assert _run(recorder_manager.suspend_recording(task_id)) is True

        assert _run(recorder_manager.discard_recording(task_id)) is True
        assert not os.path.exists(filepath)
        assert not recorder_manager.has_session(task_id)

    assert _run(recorder_manager.discard_recording(_new_task_id())) is False


def test_resume_appends_to_same_wav_across_suspend_boundary():
    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    _run(recorder_manager.set_sample_rate(task_id, 16000))
    first = b"\x01\x00" * 500
    second = b"\x02\x00" * 300
    _run(recorder_manager.add_chunk(task_id, first))

    filepath = recorder_manager._active_recordings[task_id]["filepath"]
    _run(recorder_manager.suspend_recording(task_id))
    _run(recorder_manager.resume_recording(task_id, "conn-2"))
    _run(recorder_manager.add_chunk(task_id, second))

    dest = _run(recorder_manager.stop_recording(task_id))
    assert dest is not None
    with wave.open(dest, "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.readframes(wf.getnframes()) == first + second
    os.remove(dest)
    assert not os.path.exists(filepath)


def test_grace_expiry_finalizes_suspended_session_into_pipeline(monkeypatch):
    task_id = _new_task_id()
    created = []
    submitted = []

    def fake_create_task(filename, audio_path):
        created.append({"filename": filename, "audio_path": audio_path})
        return SimpleNamespace(id=f"pipe_{len(created)}")

    monkeypatch.setattr(record_session_module, "create_task", fake_create_task)
    monkeypatch.setattr(record_session_module, "submit_pipeline", lambda tid: submitted.append(tid))

    _run(recorder_manager.start_recording(task_id))
    _run(recorder_manager.set_sample_rate(task_id, 16000))
    _run(recorder_manager.add_chunk(task_id, b"\x00\x00" * 128))
    assert _run(recorder_manager.suspend_recording(task_id)) is True

    _run(record_session_service.finalize_after_grace(task_id, 0))

    assert len(created) == 1
    assert submitted == ["pipe_1"]
    assert os.path.exists(created[0]["audio_path"])
    assert not recorder_manager.has_session(task_id)
    os.remove(created[0]["audio_path"])


def test_grace_expiry_skips_active_session(monkeypatch):
    task_id = _new_task_id()
    created = []
    monkeypatch.setattr(
        record_session_module, "create_task",
        lambda filename, audio_path: created.append(1) or SimpleNamespace(id="x"),
    )
    monkeypatch.setattr(record_session_module, "submit_pipeline", lambda tid: None)

    _run(recorder_manager.start_recording(task_id))
    _run(record_session_service.finalize_after_grace(task_id, 0))

    assert created == []
    assert recorder_manager.has_session(task_id)
    _run(recorder_manager.cancel_recording(task_id))


def test_grace_expiry_with_empty_recording_creates_no_task(monkeypatch):
    task_id = _new_task_id()
    created = []
    monkeypatch.setattr(
        record_session_module, "create_task",
        lambda filename, audio_path: created.append(1) or SimpleNamespace(id="x"),
    )
    monkeypatch.setattr(record_session_module, "submit_pipeline", lambda tid: None)

    _run(recorder_manager.start_recording(task_id))
    assert _run(recorder_manager.suspend_recording(task_id)) is True
    _run(record_session_service.finalize_after_grace(task_id, 0))

    assert created == []
    assert not recorder_manager.has_session(task_id)


def test_delete_route_discards_session_and_404s_when_absent():
    app = FastAPI()
    app.include_router(record_module.router)
    client = TestClient(app)

    resp = client.delete(f"/api/record/{_new_task_id()}")
    assert resp.status_code == 404

    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    _run(recorder_manager.set_sample_rate(task_id, 16000))
    _run(recorder_manager.add_chunk(task_id, b"\x00\x00" * 32))
    filepath = recorder_manager._active_recordings[task_id]["filepath"]

    resp = client.delete(f"/api/record/{task_id}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert not os.path.exists(filepath)
    assert not recorder_manager.has_session(task_id)


def test_config_default_and_server_key_registry():
    assert settings.reconnect_grace_seconds == 60
    from backend.app.config import SETTING_SPECS
    assert SETTING_SPECS["reconnect_grace_seconds"].caster is int
