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
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    asr_model_type: str = ""


class SettingsInfo(BaseModel):
    llm_base_url: str
    llm_model: str
    llm_api_key_set: bool = False
    asr_model_type: str
