import asyncio
import os
import time
import numpy as np

from backend.app.config import settings
from backend.app.models.schemas import (
    TaskInfo,
    TaskStatus,
    StepInfo,
    TranscriptSegment,
    TaskResult,
)
from backend.app.services.asr import create_asr


_task_store: dict[str, TaskInfo] = {}


def get_task(task_id: str) -> TaskInfo | None:
    return _task_store.get(task_id)


def create_task(filename: str, audio_path: str) -> TaskInfo:
    task = TaskInfo(filename=filename, audio_path=audio_path)
    _task_store[task.id] = task
    return task


async def run_pipeline(task_id: str):
    task = _task_store.get(task_id)
    if task is None:
        return

    task.status = TaskStatus.processing
    steps = [
        ("vad", "执行语音活动检测 (VAD)"),
        ("asr", "执行语音识别与说话人分离 (ASR + CAM++)"),
    ]

    task.progress.steps = [
        StepInfo(name=name, status="pending", message=desc)
        for name, desc in steps
    ]

    def update_step(name: str, status: str, message: str = ""):
        for s in task.progress.steps:
            if s.name == name:
                s.status = status
                s.message = message
        task.progress.current_step = name
        done = sum(1 for s in task.progress.steps if s.status == "done")
        task.progress.overall = done / len(task.progress.steps)

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

        update_step("vad", "running")
        await asyncio.sleep(0)
        update_step("vad", "done")

        update_step("asr", "running")
        await asyncio.sleep(0)
        asr_engine = create_asr(settings.asr_model_type, settings.asr_model_name)
        segments_raw = asr_engine.transcribe(audio_path, language="auto")
        update_step("asr", "done")

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

        task.result = TaskResult(
            segments=segments,
            full_text=full_text,
            duration=duration,
        )
        task.status = TaskStatus.done
        task.progress.overall = 1.0

    except Exception as e:
        task.status = TaskStatus.error
        task.error = str(e)
        for s in task.progress.steps:
            if s.status == "running":
                s.status = "error"
                s.message = str(e)
