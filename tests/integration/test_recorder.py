import os
import wave
import asyncio
import uuid

import pytest

pytestmark = pytest.mark.integration


def _run(coro):
    return asyncio.run(coro)


def _new_task_id():
    return f"test_{uuid.uuid4().hex[:8]}"


def _pcm_bytes(sample_rate: int, duration_sec: float, freq: float = 440.0) -> bytes:
    import numpy as np
    t = np.arange(int(sample_rate * duration_sec)) / sample_rate
    samples = (np.sin(2 * 3.14159 * freq * t) * 16000).astype(np.int16)
    return samples.tobytes()


def test_recorder_streams_to_disk_not_memory():
    from backend.app.services.recorder import recorder_manager

    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    rec = recorder_manager._active_recordings[task_id]

    _run(recorder_manager.add_chunk(task_id, b"\x00\x00" * 100))
    assert len(rec["pending"]) == 200
    assert rec["byte_count"] == 0
    assert rec["wf"] is None

    _run(recorder_manager.set_sample_rate(task_id, 16000))
    assert rec["wf"] is not None
    assert len(rec["pending"]) == 0
    assert rec["byte_count"] == 200

    chunk = b"\x00\x00" * 1000
    _run(recorder_manager.add_chunk(task_id, chunk))
    assert rec["byte_count"] == 200 + len(chunk)
    assert len(rec["pending"]) == 0

    final_path = _run(recorder_manager.stop_recording(task_id))
    assert final_path is not None
    assert os.path.exists(final_path)

    with wave.open(final_path, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        frames = wf.readframes(wf.getnframes())
        assert len(frames) == 200 + len(chunk)

    os.remove(final_path)
    assert task_id not in recorder_manager._active_recordings


def test_recorder_uses_actual_sample_rate_from_config():
    from backend.app.services.recorder import recorder_manager

    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    _run(recorder_manager.set_sample_rate(task_id, 48000))
    _run(recorder_manager.add_chunk(task_id, b"\x00\x00" * 100))
    final_path = _run(recorder_manager.stop_recording(task_id))

    with wave.open(final_path, "rb") as wf:
        assert wf.getframerate() == 48000
    os.remove(final_path)


def test_recorder_falls_back_to_default_if_config_never_arrives():
    from backend.app.services.recorder import recorder_manager

    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    _run(recorder_manager.add_chunk(task_id, b"\x00\x00" * 50))
    final_path = _run(recorder_manager.stop_recording(task_id))

    assert final_path is not None
    with wave.open(final_path, "rb") as wf:
        assert wf.getframerate() == 16000
    os.remove(final_path)


def test_recorder_cancel_removes_partial_file():
    from backend.app.services.recorder import recorder_manager

    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    _run(recorder_manager.set_sample_rate(task_id, 16000))
    _run(recorder_manager.add_chunk(task_id, b"\x00\x00" * 100))

    rec = recorder_manager._active_recordings[task_id]
    assert os.path.exists(rec["filepath"])

    ok = _run(recorder_manager.cancel_recording(task_id))
    assert ok is True
    assert task_id not in recorder_manager._active_recordings
    assert not os.path.exists(rec["filepath"])


def test_recorder_stop_with_no_data_returns_none_and_cleans_up():
    from backend.app.services.recorder import recorder_manager

    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    final_path = _run(recorder_manager.stop_recording(task_id))
    assert final_path is None
    assert task_id not in recorder_manager._active_recordings


def test_recorder_memory_bounded_for_long_recordings():
    from backend.app.services.recorder import recorder_manager

    task_id = _new_task_id()
    _run(recorder_manager.start_recording(task_id))
    _run(recorder_manager.set_sample_rate(task_id, 48000))

    sample_rate = 48000
    chunk = _pcm_bytes(sample_rate, 0.1)
    total_chunks = 30 * 60 * 10

    rec = recorder_manager._active_recordings[task_id]
    for _ in range(total_chunks):
        _run(recorder_manager.add_chunk(task_id, chunk))

    assert len(rec["pending"]) == 0
    assert rec["byte_count"] == total_chunks * len(chunk)

    final_path = _run(recorder_manager.stop_recording(task_id))
    assert final_path is not None
    file_size = os.path.getsize(final_path)
    expected = total_chunks * len(chunk)
    assert file_size >= expected
    os.remove(final_path)
