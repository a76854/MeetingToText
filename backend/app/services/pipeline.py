import asyncio
import os
import time
import numpy as np

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

    try:
        audio_path = task.audio_path
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        import soundfile as sf
        audio_data, sr = sf.read(audio_path, dtype="float32")
        if len(audio_data.shape) == 2:
            audio_data = audio_data.mean(axis=1)
        duration = len(audio_data) / sr

        mx = float(np.abs(audio_data).max())
        rms = float(np.sqrt(np.mean(audio_data ** 2)))
        clipped_ratio = float(np.mean(np.abs(audio_data) >= 0.99))

        if duration < 0.5:
            raise ValueError("录音时长不足 (约 0 秒)，请重新录制")
        if mx < 0.005:
            raise ValueError("音频信号极弱，可能麦克风未正确连接或静音")
        if clipped_ratio > 0.1:
            raise ValueError(
                f"音频削波严重 (max={mx:.2f}, 削波样本比={clipped_ratio:.0%})。"
                "请检查麦克风设置，降低系统输入音量或将麦克风远离音源后重试"
            )

        update_step("vad", "running", "正在分段...", overall=0.1)
        update_step("asr", "running", "加载模型并识别...", overall=0.2)

        asr_engine = get_asr(settings.asr_model_type, settings.asr_model_name)
        segments_raw = asr_engine.transcribe(audio_path, language="auto")
        update_step("vad", "done", overall=0.5)
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
        store.update_progress(task_id, TaskStatus.error, str(e))
