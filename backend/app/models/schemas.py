from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    error = "error"


class StepInfo(BaseModel):
    name: str = ""
    status: str = "pending"
    message: str = ""


class ProgressInfo(BaseModel):
    current_step: str = ""
    steps: list[StepInfo] = []
    overall: float = 0.0


class TranscriptSegment(BaseModel):
    start: float
    end: float
    speaker: str = ""
    text: str = ""


class TaskResult(BaseModel):
    segments: list[TranscriptSegment] = []
    full_text: str = ""
    duration: float = 0.0


class TaskInfo(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: TaskStatus = TaskStatus.pending
    filename: str = ""
    audio_path: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    progress: ProgressInfo = Field(default_factory=ProgressInfo)
    result: Optional[TaskResult] = None
    minutes: Optional[str] = None
    error: Optional[str] = None


class UploadResponse(BaseModel):
    task_id: str
    filename: str


class TemplateInfo(BaseModel):
    id: str
    name: str
    description: str


class GenerateRequest(BaseModel):
    task_id: str
    template_id: str = "meeting_minutes"
    custom_instructions: str = ""


class GenerateResponse(BaseModel):
    minutes: str


class SettingsUpdate(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None
    asr_model_type: str | None = None
    asr_model_name: str | None = None
    asr_needs_punc: bool | None = None
    ncpu: int | None = None
    asr_batch_size_s: int | None = None
    asr_merge_length_s: float | None = None
    asr_merge_vad: bool | None = None
    asr_max_single_segment_time: int | None = None
    streaming_asr_enabled: bool | None = None
    streaming_asr_model_name: str | None = None
    browser_noise_suppression: bool | None = None
    audio_source: str | None = None


# C7: response model only — GET /settings populates every field from
# backend/app/config.py, so no inline defaults here (they would drift).
class SettingsInfo(BaseModel):
    llm_base_url: str
    llm_model: str
    llm_api_key_set: bool
    llm_temperature: float
    llm_max_tokens: int
    asr_model_type: str
    asr_model_name: str
    asr_needs_punc: bool
    ncpu: int
    asr_batch_size_s: int
    asr_merge_length_s: float
    asr_merge_vad: bool
    asr_max_single_segment_time: int
    streaming_asr_enabled: bool
    streaming_asr_model_name: str
    browser_noise_suppression: bool
    audio_source: str
