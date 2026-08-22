import os
import wave
import time
import shutil

from backend.app.config import settings


class RecorderManager:
    def __init__(self):
        self._active_recordings: dict[str, dict] = {}

    async def start_recording(self, task_id: str) -> str:
        filepath = os.path.join(settings.temp_dir, f"record_{task_id}_{int(time.time())}.wav")
        self._active_recordings[task_id] = {
            "filepath": filepath,
            "wf": None,
            "pending": bytearray(),
            "sample_rate": settings.target_sr,
            "sample_rate_set": False,
            "channels": 1,
            "sample_width": 2,
            "byte_count": 0,
            "started_at": time.time(),
        }
        return filepath

    async def set_sample_rate(self, task_id: str, sample_rate: int):
        rec = self._active_recordings.get(task_id)
        if rec is None or rec["sample_rate_set"]:
            return
        if sample_rate <= 0:
            return
        rec["sample_rate"] = sample_rate
        rec["sample_rate_set"] = True
        wf = wave.open(rec["filepath"], "wb")
        wf.setnchannels(rec["channels"])
        wf.setsampwidth(rec["sample_width"])
        wf.setframerate(sample_rate)
        if rec["pending"]:
            wf.writeframes(bytes(rec["pending"]))
            rec["byte_count"] += len(rec["pending"])
            rec["pending"].clear()
        rec["wf"] = wf

    async def add_chunk(self, task_id: str, chunk: bytes):
        rec = self._active_recordings.get(task_id)
        if rec is None or not chunk:
            return
        wf = rec["wf"]
        if wf is None:
            rec["pending"].extend(chunk)
        else:
            wf.writeframes(chunk)
            rec["byte_count"] += len(chunk)

    async def stop_recording(self, task_id: str) -> str | None:
        rec = self._active_recordings.pop(task_id, None)
        if rec is None:
            return None
        filepath = rec["filepath"]
        wf = rec["wf"]
        if wf is not None:
            wf.close()
        elif rec["pending"]:
            wf = wave.open(filepath, "wb")
            wf.setnchannels(rec["channels"])
            wf.setsampwidth(rec["sample_width"])
            wf.setframerate(rec["sample_rate"])
            wf.writeframes(bytes(rec["pending"]))
            wf.close()
            rec["byte_count"] += len(rec["pending"])

        if rec["byte_count"] == 0:
            try:
                os.remove(filepath)
            except OSError:
                pass
            return None

        dest = os.path.join(settings.upload_dir, os.path.basename(filepath))
        shutil.move(filepath, dest)
        return dest

    async def cancel_recording(self, task_id: str) -> bool:
        rec = self._active_recordings.pop(task_id, None)
        if rec is None:
            return False
        wf = rec["wf"]
        if wf is not None:
            try:
                wf.close()
            except Exception:
                pass
        try:
            os.remove(rec["filepath"])
        except OSError:
            pass
        rec["pending"].clear()
        return True

    def has_session(self, task_id: str) -> bool:
        return task_id in self._active_recordings


recorder_manager = RecorderManager()
