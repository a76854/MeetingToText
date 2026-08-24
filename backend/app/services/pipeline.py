import os
import warnings
import tempfile
import logging
from concurrent.futures import ThreadPoolExecutor, Future
import numpy as np
import soundfile as sf
import librosa

logger = logging.getLogger(__name__)

from backend.app.config import settings
from backend.app.models.schemas import (
    TaskStatus,
    StepInfo,
    ProgressInfo,
    TranscriptSegment,
    TaskResult,
)
from backend.app.services.asr import get_asr
from backend.app.services.store import TaskStore, get_store


PIPELINE_STEPS = [
    ("vad", "执行语音活动检测 (VAD)"),
    ("asr", "执行语音识别与说话人分离 (ASR + CAM++)"),
]

# Audio-quality gate thresholds. The exact values AND the user-facing error
# messages they guard are pinned byte-for-byte by tests/test_pipeline_quality.py.
MIN_DURATION_S = 0.5              # reject recordings shorter than this
SILENCE_AMPLITUDE_THRESHOLD = 0.005  # reject nearly-silent audio below this peak
CLIP_ABS_LIMIT = 0.99             # samples at/above this amplitude count as clipped
CLIP_RATIO_LIMIT = 0.1            # reject when clipped-sample ratio exceeds this

# Progress fractions persisted at each pipeline stage (first save is
# PROGRESS_INITIAL from _initial_progress, final save is PROGRESS_COMPLETE).
PROGRESS_INITIAL = 0.0
PROGRESS_AFTER_VAD_RUNNING = 0.3
PROGRESS_AFTER_ASR_RUNNING = 0.35
PROGRESS_AFTER_VAD_DONE = 0.8
PROGRESS_COMPLETE = 1.0


def format_transcript_text(segments, separator: str) -> str:
    """Join transcript segments into plain text.

    Each line is ``[speaker] text`` when a speaker is present, otherwise bare
    ``text``. The separator differs by consumer: stored/rebuilt ``full_text``
    uses ``"\\n\\n"``, TXT export uses a single ``"\\n"``.
    """
    return separator.join(
        f"[{seg.speaker}] {seg.text}" if seg.speaker else seg.text for seg in segments
    )

pipeline_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")

_pipeline_futures: dict[str, Future] = {}
_cancelled: set[str] = set()


def _check_cancelled(task_id: str) -> bool:
    if task_id in _cancelled:
        logger.info(f"pipeline for task={task_id} was cancelled, aborting")
        return True
    return False


def _cleanup_cancelled(task_id: str) -> None:
    _cancelled.discard(task_id)


def submit_pipeline(task_id: str) -> Future:
    fut = pipeline_executor.submit(run_pipeline, task_id)
    _pipeline_futures[task_id] = fut
    fut.add_done_callback(lambda _: _pipeline_futures.pop(task_id, None))
    return fut


def cancel_pipeline(task_id: str) -> bool:
    _cancelled.add(task_id)
    fut = _pipeline_futures.pop(task_id, None)
    if fut is not None and not fut.done():
        cancelled = fut.cancel()
        if cancelled:
            logger.info(f"cancelled pipeline for task={task_id}")
        return cancelled
    return False


def _initial_progress() -> ProgressInfo:
    return ProgressInfo(
        current_step="",
        steps=[StepInfo(name=name, status="pending", message=desc) for name, desc in PIPELINE_STEPS],
        overall=PROGRESS_INITIAL,
    )


class ProgressTracker:
    """Mutates and persists ``ProgressInfo`` for one pipeline run.

    Extracted from the ``update_step`` closure that used to live inside
    ``run_pipeline``: each method replays the exact same mutation order and
    the exact same ``store.save_progress`` call, so progress fractions
    observed by tests/test_pipeline_quality.py stay identical.
    """

    def __init__(self, store: TaskStore, task_id: str, progress: ProgressInfo) -> None:
        self._store = store
        self._task_id = task_id
        self._progress = progress

    def running(self, name: str, message: str = "", overall: float | None = None) -> None:
        for step in self._progress.steps:
            if step.name == name:
                step.status = "running"
                if message:
                    step.message = message
                break
        self._progress.current_step = name
        if overall is not None:
            self._progress.overall = overall
        self._store.save_progress(self._task_id, self._progress)

    def done(self, name: str, message: str = "", overall: float | None = None) -> None:
        for step in self._progress.steps:
            if step.name == name:
                step.status = "done"
                if message:
                    step.message = message
                break
        done_count = sum(1 for s in self._progress.steps if s.status == "done")
        self._progress.overall = done_count / max(len(self._progress.steps), 1)
        if overall is not None:
            self._progress.overall = overall
        self._store.save_progress(self._task_id, self._progress)


def _read_mono(path: str) -> tuple[np.ndarray, int]:
    """Read audio via soundfile as float32, collapsing multi-channel to mono."""
    data, sr = sf.read(path, dtype="float32")
    if len(data.shape) == 2:
        data = data.mean(axis=1)
    return data, sr


def _prepare_asr_input(audio_path: str) -> tuple[str, int, float]:
    """Load audio, resample to 16kHz if needed, write temp file for ASR.

    Returns (asr_input_path, original_sr, duration_seconds).
    """
    try:
        audio_data, original_sr = _read_mono(audio_path)
    except Exception:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="PySoundFile failed")
            warnings.filterwarnings("ignore", category=FutureWarning, module="librosa")
            audio_data, original_sr = librosa.load(audio_path, sr=None, mono=True)

    duration = len(audio_data) / original_sr
    target_sr = settings.target_sr

    if original_sr == target_sr:
        return audio_path, original_sr, duration

    logger.info(
        f"Resampling {original_sr}Hz -> {target_sr}Hz ({duration:.1f}s)"
    )
    resampled = librosa.resample(audio_data, orig_sr=original_sr, target_sr=target_sr)
    fd, tmp_path = tempfile.mkstemp(prefix="asr_16k_", suffix=".wav", dir=settings.temp_dir)
    os.close(fd)
    sf.write(tmp_path, resampled, target_sr, subtype="PCM_16")
    return tmp_path, original_sr, duration


def check_audio_quality(data: np.ndarray, sr: int, duration: float) -> None:
    """Reject unusable audio before ASR runs.

    Computes quick peak/RMS/clip stats on the mono samples and enforces the
    three quality gates. Every ValueError carries user-facing Chinese copy
    that is pinned byte-for-byte by tests/test_pipeline_quality.py — do not
    reword without updating that lock.
    """
    mx = float(np.abs(data).max())
    rms = float(np.sqrt(np.mean(data ** 2)))
    clipped_ratio = float(np.mean(np.abs(data) >= CLIP_ABS_LIMIT))

    logger.info(f"asr_sr={sr}Hz dur={duration:.1f}s mx={mx:.4f} rms={rms:.4f}")

    if duration < MIN_DURATION_S:
        raise ValueError("录音时长不足 (约 0 秒)，请重新录制")
    if mx < SILENCE_AMPLITUDE_THRESHOLD:
        raise ValueError("音频信号极弱，可能麦克风未正确连接或静音")
    if clipped_ratio > CLIP_RATIO_LIMIT:
        raise ValueError(
            f"音频削波严重 (max={mx:.2f}, 削波样本比={clipped_ratio:.0%})。"
            "请检查麦克风设置，降低系统输入音量或将麦克风远离音源后重试"
        )


def run_pipeline(task_id: str):
    if _check_cancelled(task_id):
        return

    store = get_store()
    task = store.get(task_id)
    if task is None:
        return
    progress = _initial_progress()
    store.save_progress(task_id, progress)
    store.update_progress(task_id, TaskStatus.processing)
    tracker = ProgressTracker(store, task_id, progress)

    asr_temp_path: str | None = None
    original_audio_path: str | None = None
    try:
        audio_path = task.audio_path
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        original_audio_path = audio_path
        asr_input, original_sr, duration = _prepare_asr_input(audio_path)
        if asr_input != audio_path:
            asr_temp_path = asr_input
        check_data, check_sr = _read_mono(asr_input)
        logger.info(f"task={task_id} file={audio_path} orig_sr={original_sr}Hz")
        check_audio_quality(check_data, check_sr, duration)
        tracker.running("vad", "正在分段...", overall=PROGRESS_AFTER_VAD_RUNNING)
        tracker.running("asr", "加载模型并识别...", overall=PROGRESS_AFTER_ASR_RUNNING)
        if _check_cancelled(task_id):
            return

        asr_engine = get_asr(settings.asr_model_type, settings.asr_model_name)
        segments_raw = asr_engine.transcribe(asr_input, language="auto")
        logger.info(f"ASR returned {len(segments_raw)} segments for task={task_id}")
        # Fallback: if resampled input yielded 0 segments, retry with the original file
        if not segments_raw and asr_temp_path is not None:
            logger.info("Resampled input empty, retrying with original audio")
            segments_raw = asr_engine.transcribe(original_audio_path, language="auto")
            logger.info(f"Original-audio ASR returned {len(segments_raw)} segments")
        if not segments_raw:
            raise RuntimeError(
                "未能识别到语音内容，请检查音频是否有效（可能静音、语言不支持或麦克风未正常工作）"
            )
        tracker.done("vad", overall=PROGRESS_AFTER_VAD_DONE)
        tracker.done("asr", f"识别完成，共 {len(segments_raw)} 段", overall=PROGRESS_COMPLETE)
        segments = [
            TranscriptSegment(
                start=s["start"],
                end=s["end"],
                speaker=s.get("speaker", ""),
                text=s["text"],
            )
            for s in segments_raw
        ]
        full_text = format_transcript_text(segments, "\n\n")
        result = TaskResult(segments=segments, full_text=full_text, duration=duration)
        store.save_result(task_id, result)
    except Exception as e:
        logger.error(f"task={task_id} failed: {e}")
        store.update_progress(task_id, TaskStatus.error, str(e))
    finally:
        _cleanup_cancelled(task_id)
        if asr_temp_path and os.path.exists(asr_temp_path):
            try:
                os.remove(asr_temp_path)
            except OSError:
                pass
