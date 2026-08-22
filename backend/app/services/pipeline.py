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
    TaskInfo,
    TaskStatus,
    StepInfo,
    ProgressInfo,
    TranscriptSegment,
    TaskResult,
)
from backend.app.services.asr import get_asr
from backend.app.services.store import get_store


PIPELINE_STEPS = [
    ("vad", "执行语音活动检测 (VAD)"),
    ("asr", "执行语音识别与说话人分离 (ASR + CAM++)"),
]


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
        overall=0.0,
    )


def get_task(task_id: str) -> TaskInfo | None:
    return get_store().get(task_id)


def create_task(filename: str, audio_path: str) -> TaskInfo:
    task = TaskInfo(filename=filename, audio_path=audio_path)
    return get_store().create(task)


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

    def update_step(name: str, status: str, message: str = "", overall: float | None = None) -> None:
        for step in progress.steps:
            if step.name == name:
                step.status = status
                if message:
                    step.message = message
                break
        if status == "running":
            progress.current_step = name
        elif status == "done":
            done_count = sum(1 for s in progress.steps if s.status == "done")
            progress.overall = done_count / max(len(progress.steps), 1)
        if overall is not None:
            progress.overall = overall
        store.save_progress(task_id, progress)

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

        # Quick stats on the (resampled) audio we're about to ASR
        check_data, check_sr = _read_mono(asr_input)
        mx = float(np.abs(check_data).max())
        rms = float(np.sqrt(np.mean(check_data ** 2)))
        clipped_ratio = float(np.mean(np.abs(check_data) >= 0.99))

        logger.info(
            f"task={task_id} file={audio_path} "
            f"orig_sr={original_sr}Hz asr_sr={check_sr}Hz "
            f"dur={duration:.1f}s mx={mx:.4f} rms={rms:.4f}"
        )

        if duration < 0.5:
            raise ValueError("录音时长不足 (约 0 秒)，请重新录制")
        if mx < 0.005:
            raise ValueError("音频信号极弱，可能麦克风未正确连接或静音")
        if clipped_ratio > 0.1:
            raise ValueError(
                f"音频削波严重 (max={mx:.2f}, 削波样本比={clipped_ratio:.0%})。"
                "请检查麦克风设置，降低系统输入音量或将麦克风远离音源后重试"
            )

        update_step("vad", "running", "正在分段...", overall=0.3)
        update_step("asr", "running", "加载模型并识别...", overall=0.35)

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

        update_step("vad", "done", overall=0.8)
        update_step("asr", "done", f"识别完成，共 {len(segments_raw)} 段", overall=1.0)

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

        result = TaskResult(
            segments=segments,
            full_text=full_text,
            duration=duration,
        )
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
