import contextlib
import os
import shutil
import time
import wave
from datetime import datetime

from backend.app.config import settings

# Session lifecycle (reconnect-resume):
#   active    - a live websocket owns the session and appends audio
#   suspended - owning websocket dropped; grace window before finalize
STATE_ACTIVE = "active"
STATE_SUSPENDED = "suspended"


class RecorderManager:
    def __init__(self):
        self._active_recordings: dict[str, dict] = {}

    async def start_recording(self, task_id: str) -> str:
        existing = self._active_recordings.get(task_id)
        if existing is not None:
            return existing["filepath"]
        filepath = os.path.join(
            settings.temp_dir, f"record_{task_id}_{datetime.now().strftime('%y%m%d%H%M%S')}.wav"
        )
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
            "state": STATE_ACTIVE,
            "owner": None,
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
            with contextlib.suppress(OSError):
                os.remove(filepath)
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
            with contextlib.suppress(Exception):
                wf.close()
        with contextlib.suppress(OSError):
            os.remove(rec["filepath"])
        rec["pending"].clear()
        return True

    def has_session(self, task_id: str) -> bool:
        return task_id in self._active_recordings

    # ---- reconnect/resume state machine ----

    def get_session_state(self, task_id: str) -> str | None:
        rec = self._active_recordings.get(task_id)
        return rec["state"] if rec else None

    def attach_owner(self, task_id: str, owner_id) -> bool:
        """Bind a connection to a session (single-owner guard).

        False when the session is missing or actively owned by another
        connection; adopting a suspended session always succeeds.
        """
        rec = self._active_recordings.get(task_id)
        if rec is None:
            return False
        current = rec.get("owner")
        if current is not None and current != owner_id:
            return False
        rec["owner"] = owner_id
        rec["state"] = STATE_ACTIVE
        return True

    def detach_owner(self, task_id: str, owner_id) -> None:
        rec = self._active_recordings.get(task_id)
        if rec is not None and rec.get("owner") == owner_id:
            rec["owner"] = None

    async def suspend_recording(self, task_id: str) -> bool:
        """Active -> suspended (ws dropped without stop/discard)."""
        rec = self._active_recordings.get(task_id)
        if rec is None or rec["state"] != STATE_ACTIVE:
            return False
        rec["state"] = STATE_SUSPENDED
        rec["owner"] = None
        return True

    async def resume_recording(self, task_id: str, owner_id=None) -> bool:
        """Suspended -> active; same wav keeps appending."""
        rec = self._active_recordings.get(task_id)
        if rec is None or rec["state"] != STATE_SUSPENDED:
            return False
        rec["state"] = STATE_ACTIVE
        rec["owner"] = owner_id
        return True

    async def discard_recording(self, task_id: str) -> bool:
        """Delete file + session without creating a task (any state)."""
        return await self.cancel_recording(task_id)


recorder_manager = RecorderManager()
