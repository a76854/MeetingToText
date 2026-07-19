import asyncio
import os
import time
import tempfile
import numpy as np
import soundfile as sf
import librosa

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
    ("queue", "排队等待"),
    ("vad", "执行语音活动检测 (VAD)"),
    ("asr", "执行语音识别与说话人分离 (ASR + CAM++)"),
]

_asr_lock = asyncio.Lock()


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


def _prepare_asr_input(audio_path: str) -> tuple[str, int, float]:
    """Load audio, resample to 16kHz if needed, write temp file for ASR.

    Returns (asr_input_path, original_sr, duration_seconds).
    """
    try:
        audio_data, original_sr = sf.read(audio_path, dtype="float32")
    except Exception as e:
        raise ValueError(f"无法读取音频文件: {e}")

    if len(audio_data.shape) == 2:
        audio_data = audio_data.mean(axis=1)

    duration = len(audio_data) / original_sr

    if original_sr == 16000:
        return audio_path, original_sr, duration

    print(f"[pipeline] Resampling {original_sr}Hz -> 16000Hz ({duration:.1f}s)")
    resampled = librosa.resample(audio_data, orig_sr=original_sr, target_sr=16000)
    fd, tmp_path = tempfile.mkstemp(prefix="asr_16k_", suffix=".wav", dir=settings.temp_dir)
    os.close(fd)
    sf.write(tmp_path, resampled, 16000, subtype="PCM_16")
    return tmp_path, original_sr, duration


async def run_pipeline(task_id: str):
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
        check_data, check_sr = sf.read(asr_input, dtype="float32")
        if len(check_data.shape) == 2:
            check_data = check_data.mean(axis=1)
        mx = float(np.abs(check_data).max())
        rms = float(np.sqrt(np.mean(check_data ** 2)))
        clipped_ratio = float(np.mean(np.abs(check_data) >= 0.99))

        print(
            f"[pipeline] task={task_id} file={audio_path} "
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

        update_step("queue", "running", "等待前序任务完成...", overall=0.15)

        async with _asr_lock:
            update_step("queue", "done", overall=0.2)

            update_step("vad", "running", "正在分段...", overall=0.25)
            update_step("asr", "running", "加载模型并识别...", overall=0.3)

            asr_engine = get_asr(settings.asr_model_type, settings.asr_model_name)
            segments_raw = asr_engine.transcribe(asr_input, language="auto")
            print(f"[pipeline] ASR returned {len(segments_raw)} segments for task={task_id}")

            # Fallback: if resampled input yielded 0 segments, retry with the original file
            if not segments_raw and asr_temp_path is not None:
                print("[pipeline] Resampled input empty, retrying with original audio")
                segments_raw = asr_engine.transcribe(original_audio_path, language="auto")
                print(f"[pipeline] Original-audio ASR returned {len(segments_raw)} segments")

            if not segments_raw:
                print(f"[pipeline] WARNING: ASR produced 0 segments for task={task_id}; "
                      f"audio may be too quiet, in unsupported language, or the model failed to load")

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

        full_text_parts = []
        for seg in segments:
            speaker_label = f"[{seg.speaker}] " if seg.speaker else ""
            full_text_parts.append(f"{speaker_label}{seg.text}")
        full_text = "\n\n".join(full_text_parts)

        result = TaskResult(
            segments=segments,
            full_text=full_text,
            duration=duration,
        )
        store.save_result(task_id, result)

    except Exception as e:
        print(f"[pipeline] task={task_id} failed: {e}")
        store.update_progress(task_id, TaskStatus.error, str(e))
    finally:
        if asr_temp_path and os.path.exists(asr_temp_path):
            try:
                os.remove(asr_temp_path)
            except OSError:
                pass
