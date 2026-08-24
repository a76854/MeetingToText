"""Hermetic tests pinning the audio-quality gates and resample prep in
``backend/app/services/pipeline.py``.

These gates currently have zero coverage and are scheduled for a later
refactor (todo 17: named constants + extracted ``check_audio_quality``).
This file locks TODAY's behavior — exact user-facing Chinese error strings,
magic thresholds, and progress fractions — so the refactor can verify
zero behavior change by pointing these tests at the new constant names.

Every test is hermetic: synthetic numpy waveforms written via soundfile,
``settings.data_dir`` redirected to ``tmp_path`` (following the fixture
pattern in tests/test_reconnect_ws.py), the ``TaskStore`` singleton reset
to a fresh database, and ``pipeline.get_asr`` replaced with an in-memory
fake so no real FunASR model is ever touched.

Behavioral seams observed:
- ``run_pipeline`` catches every exception and stores it via
  ``store.update_progress(task_id, TaskStatus.error, str(e))``, so gate
  failures are asserted through the STORED TASK ERROR (:237-239).
- The three quality gates (:184-192) run BEFORE ASR engine selection
  (:200), so a fake engine whose ``transcribe`` raises proves the gate
  fired first (``fake.calls == 0``).
- ``_prepare_asr_input`` writes its resampled temp file via
  ``tempfile.mkstemp(dir=settings.temp_dir)`` — hence the mandatory
  ``settings.temp_dir`` redirect.
"""

import os

import numpy as np
import pytest
import soundfile as sf

from backend.app import config
from backend.app.config import settings
import backend.app.services.store as store_module
from backend.app.services.store import get_store
from backend.app.services import pipeline
from backend.app.models.schemas import TaskInfo, TaskStatus

# Magic thresholds under test — aliases to the product constants (todo 17
# named them without changing values; these tests remain the referee).
MIN_DURATION_S = pipeline.MIN_DURATION_S
SILENCE_AMPLITUDE = pipeline.SILENCE_AMPLITUDE_THRESHOLD
CLIP_ABS_LIMIT = pipeline.CLIP_ABS_LIMIT
CLIP_RATIO_LIMIT = pipeline.CLIP_RATIO_LIMIT
PROGRESS_OVERALLS = [
    pipeline.PROGRESS_INITIAL,
    pipeline.PROGRESS_AFTER_VAD_RUNNING,
    pipeline.PROGRESS_AFTER_ASR_RUNNING,
    pipeline.PROGRESS_AFTER_VAD_DONE,
    pipeline.PROGRESS_COMPLETE,
]


# ---------------------------------------------------------------- fixtures


@pytest.fixture()
def pipeline_env(monkeypatch, tmp_path):
    """Redirect data_dir to tmp_path and reset the TaskStore singleton.

    temp_dir/upload_dir/db_path are derived properties of data_dir, so one
    monkeypatch covers all of them (same trick as test_reconnect_ws.py).
    The fresh singleton gets built lazily by get_store() against the
    redirected db_path; monkeypatch restores the original _store value on
    teardown so later tests keep their own view.
    """
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    os.makedirs(settings.temp_dir, exist_ok=True)
    os.makedirs(settings.upload_dir, exist_ok=True)
    monkeypatch.setattr(store_module, "_store", None)
    return tmp_path


class _FakeASR:
    """In-memory ASR engine substitute.

    ``segments=None`` means the engine must NOT be reached (used by the
    three failure tests — the gates raise before engine selection). A
    reached-but-forbidden engine raises so the stored error can never
    accidentally match the expected Chinese gate message.
    """

    def __init__(self, segments=None):
        self.segments = segments
        self.calls = 0

    def transcribe(self, path, language="auto"):
        self.calls += 1
        if self.segments is None:
            raise AssertionError("quality gate must fire before ASR engine selection")
        return self.segments


# ---------------------------------------------------------------- helpers


def _write_wav(tmp_path, name, data, sr):
    path = tmp_path / name
    sf.write(str(path), data, sr)
    return str(path)


def _make_task(tmp_path, name, data, sr):
    """Write a synthetic WAV into tmp_path and create a persisted task for it."""
    audio_path = _write_wav(tmp_path, name, data, sr)
    task = TaskInfo(filename=name, audio_path=audio_path)
    return get_store().create(task)


def _install_fake_asr(monkeypatch, segments=None):
    fake = _FakeASR(segments)
    monkeypatch.setattr(
        pipeline, "get_asr", lambda *args, **kwargs: fake
    )
    return fake


def _sine(seconds, sr, amplitude, freq=440.0):
    t = np.arange(int(seconds * sr)) / sr
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _assert_stored_error(task_id, expected_message):
    stored = get_store().get(task_id)
    assert stored is not None
    assert stored.status == TaskStatus.error
    # Exact user-facing copy — these strings must survive the refactor
    # byte-for-byte (they are shown to users; this file is the lock).
    assert stored.error == expected_message
    return stored


# ---------------------------------------------------------------- quality gates


def test_short_audio_rejected(pipeline_env, monkeypatch):
    """duration < 0.5s must surface the exact 录音时长不足 error."""
    data = _sine(seconds=0.4, sr=settings.target_sr, amplitude=0.5)
    task = _make_task(pipeline_env, "short.wav", data, settings.target_sr)
    fake = _install_fake_asr(monkeypatch)

    pipeline.run_pipeline(task.id)

    _assert_stored_error(task.id, "录音时长不足 (约 0 秒)，请重新录制")
    assert fake.calls == 0  # gate fires before ASR engine selection


def test_near_silent_audio_rejected(pipeline_env, monkeypatch):
    """max amplitude < 0.005 must surface the exact 极弱/静音 error."""
    data = _sine(seconds=1.0, sr=settings.target_sr, amplitude=0.002)
    task = _make_task(pipeline_env, "quiet.wav", data, settings.target_sr)
    fake = _install_fake_asr(monkeypatch)

    pipeline.run_pipeline(task.id)

    _assert_stored_error(task.id, "音频信号极弱，可能麦克风未正确连接或静音")
    assert fake.calls == 0


def test_clipped_audio_rejected(pipeline_env, monkeypatch):
    """>=0.99 sample ratio > 0.1 must surface the exact 削波 error.

    A full-scale square wave (±1.0) makes mx == 1.00 and ratio == 100%
    deterministically, so the computed values inside the f-string are
    assertable exactly.
    """
    sr = settings.target_sr
    t = np.arange(int(1.0 * sr)) / sr
    data = np.where(np.sin(2 * np.pi * 440.0 * t) >= 0, 1.0, -1.0).astype(np.float32)
    task = _make_task(pipeline_env, "clipped.wav", data, sr)
    fake = _install_fake_asr(monkeypatch)

    pipeline.run_pipeline(task.id)

    _assert_stored_error(
        task.id,
        "音频削波严重 (max=1.00, 削波样本比=100%)。"
        "请检查麦克风设置，降低系统输入音量或将麦克风远离音源后重试",
    )
    assert fake.calls == 0


def test_healthy_sine_passes_gates_to_asr(pipeline_env, monkeypatch):
    """A clean 1s sine must clear all gates, reach ASR, and finish done."""
    sr = settings.target_sr
    data = _sine(seconds=1.0, sr=sr, amplitude=0.5)
    task = _make_task(pipeline_env, "healthy.wav", data, sr)
    fake = _install_fake_asr(
        monkeypatch,
        segments=[{"start": 0.0, "end": 1.0, "speaker": "说话人1", "text": "测试内容"}],
    )

    # Spy on progress saves to pin the overall fractions 0.0/0.3/0.35/0.8/1.0
    # (magic numbers at pipeline.py:194-216, to become constants in todo 17).
    store = get_store()
    saved_overalls = []
    original_save = store.save_progress

    def _spy(task_id, progress):
        saved_overalls.append(progress.model_copy(deep=True).overall)
        original_save(task_id, progress)

    monkeypatch.setattr(store, "save_progress", _spy)

    pipeline.run_pipeline(task.id)

    stored = get_store().get(task.id)
    assert stored is not None
    assert stored.status == TaskStatus.done
    assert stored.error is None
    assert fake.calls == 1
    assert stored.result is not None
    assert stored.result.duration == pytest.approx(1.0)
    assert stored.result.full_text == "[说话人1] 测试内容"
    assert saved_overalls == PROGRESS_OVERALLS


# ---------------------------------------------------------------- resample prep


def test_prepare_asr_input_collapses_stereo_and_resamples(pipeline_env):
    """Stereo 44.1kHz input -> mono mean collapse -> 16kHz temp file in the
    REDIRECTED temp dir (never the real data/temp)."""
    sr = 44100
    t = np.arange(sr) / sr  # exactly 1.0s
    left = 0.5 * np.sin(2 * np.pi * 440.0 * t)
    right = 0.25 * np.sin(2 * np.pi * 440.0 * t)  # same phase, different level
    stereo = np.stack([left, right], axis=1).astype(np.float32)
    audio_path = _write_wav(pipeline_env, "stereo44.wav", stereo, sr)

    out_path, original_sr, duration = pipeline._prepare_asr_input(audio_path)

    assert out_path != audio_path
    assert os.path.dirname(out_path) == settings.temp_dir  # redirected, not real
    assert original_sr == sr
    assert duration == pytest.approx(1.0)

    data_read, out_sr = sf.read(out_path, dtype="float32")
    assert out_sr == settings.target_sr
    assert data_read.ndim == 1  # channels collapsed
    assert len(data_read) == settings.target_sr  # 1.0s at 16kHz

    # Same resample math applied to the channel mean (PCM_16 quantization in
    # the temp write allows ~2e-4 slack). A wrong collapse (e.g. using only
    # one channel) would deviate by ~0.125 amplitude and fail this check.
    import librosa

    expected = librosa.resample(
        (left + right) / 2, orig_sr=sr, target_sr=settings.target_sr
    )
    assert np.allclose(data_read, expected, atol=2e-4)


@pytest.mark.parametrize("channels", [1, 2], ids=["mono", "stereo"])
def test_prepare_asr_input_returns_original_path_when_sr_matches(pipeline_env, channels):
    """When input sr == target_sr, the original path is returned untouched
    and no temp file is created."""
    sr = settings.target_sr
    t = np.arange(sr) / sr
    mono = (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    data = mono if channels == 1 else np.stack([mono, mono * 0.5], axis=1)
    audio_path = _write_wav(pipeline_env, f"src{sr}-{channels}ch.wav", data, sr)

    before = set(os.listdir(settings.temp_dir))
    out_path, original_sr, duration = pipeline._prepare_asr_input(audio_path)

    assert out_path == audio_path  # untouched
    assert original_sr == sr
    assert duration == pytest.approx(1.0)
    assert set(os.listdir(settings.temp_dir)) == before  # no temp file written


def test_read_mono_collapses_stereo_to_channel_mean(pipeline_env):
    """Direct seam: _read_mono averages channels into 1-D float32."""
    sr = settings.target_sr
    n = sr // 2  # 0.5s
    left = np.full(n, 0.8, dtype=np.float32)
    right = np.full(n, 0.2, dtype=np.float32)
    stereo_path = _write_wav(
        pipeline_env, "const-stereo.wav", np.stack([left, right], axis=1), sr
    )

    data, read_sr = pipeline._read_mono(stereo_path)

    assert read_sr == sr
    assert data.ndim == 1
    assert len(data) == n
    # soundfile quantizes float WAV writes (~1.5e-5 here), so use a tolerance
    # that still cleanly discriminates mean(0.8,0.2)=0.5 from either channel.
    assert np.allclose(data, 0.5, atol=1e-3)  # mean(0.8, 0.2)


# ---------------------------------------------------------------- hermeticity


def test_pipeline_writes_nothing_to_real_data_dir(pipeline_env, monkeypatch):
    """Snapshot guard: even the resample path (which creates a temp file)
    must not touch the REAL data/temp directory."""
    real_temp_dir = os.path.join(config.DATA_DIR, "temp")
    before = sorted(os.listdir(real_temp_dir))

    sr = 44100
    t = np.arange(int(1.5 * sr)) / sr
    stereo = np.stack(
        [0.5 * np.sin(2 * np.pi * 440.0 * t), 0.5 * np.sin(2 * np.pi * 330.0 * t)],
        axis=1,
    ).astype(np.float32)
    task = _make_task(pipeline_env, "resample-hermetic.wav", stereo, sr)
    _install_fake_asr(
        monkeypatch,
        segments=[{"start": 0.0, "end": 1.5, "speaker": "说话人1", "text": "测试"}],
    )

    pipeline.run_pipeline(task.id)

    assert sorted(os.listdir(real_temp_dir)) == before
    # ...while the redirected temp dir DID receive the resampled file.
    leftovers = [f for f in os.listdir(settings.temp_dir) if f.startswith("asr_16k_")]
    assert leftovers == []  # run_pipeline removes its temp file in finally
