import os
import asyncio
import wave
import struct
import time
from pathlib import Path

from backend.app.config import settings


class RecorderManager:
    def __init__(self):
        self._active_recordings: dict[str, dict] = {}

    async def start_recording(self, task_id: str) -> str:
        filepath = os.path.join(settings.temp_dir, f"record_{task_id}_{int(time.time())}.wav")
        self._active_recordings[task_id] = {
            "filepath": filepath,
            "chunks": [],
            "sample_rate": settings.target_sr,
            "sample_rate_confirmed": False,
            "channels": 1,
            "sample_width": 2,
            "started_at": time.time(),
        }
        return filepath

    async def set_sample_rate(self, task_id: str, sample_rate: int):
        rec = self._active_recordings.get(task_id)
        if rec is None:
            return
        if rec["sample_rate_confirmed"]:
            return
        if sample_rate <= 0:
            return
        rec["sample_rate"] = sample_rate
        rec["sample_rate_confirmed"] = True

    async def add_chunk(self, task_id: str, chunk: bytes):
        rec = self._active_recordings.get(task_id)
        if rec is None:
            return
        rec["chunks"].append(chunk)

    async def stop_recording(self, task_id: str) -> str | None:
        rec = self._active_recordings.pop(task_id, None)
        if rec is None:
            return None
        filepath = rec["filepath"]
        all_data = b"".join(rec["chunks"])
        if not all_data:
            return None
        with wave.open(filepath, "wb") as wf:
            wf.setnchannels(rec["channels"])
            wf.setsampwidth(rec["sample_width"])
            wf.setframerate(rec["sample_rate"])
            wf.writeframes(all_data)
        import shutil
        dest = os.path.join(settings.upload_dir, os.path.basename(filepath))
        shutil.move(filepath, dest)
        return dest

    async def cancel_recording(self, task_id: str) -> bool:
        rec = self._active_recordings.pop(task_id, None)
        if rec is None:
            return False
        # Chunks were held in memory only; no file exists yet -> nothing to clean up
        return True

    def has_session(self, task_id: str) -> bool:
        return task_id in self._active_recordings


recorder_manager = RecorderManager()
