import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
os.environ.setdefault("MODELSCOPE_CACHE", os.path.join(DATA_DIR, "models"))


def set_cpu_threads(ncpu: int) -> int:
    cpu_count = os.cpu_count() or 4
    n = ncpu if ncpu > 0 else cpu_count
    n = min(n, cpu_count)
    os.environ["OMP_NUM_THREADS"] = str(n)
    os.environ["MKL_NUM_THREADS"] = str(n)
    try:
        import torch
        torch.set_num_threads(n)
    except ImportError:
        pass
    return n


class Settings(BaseSettings):
    model_config = {
        "protected_namespaces": ("settings_",),
        "env_prefix": "MTT_",
    }

    data_dir: str = DATA_DIR

    target_sr: int = 16000
    max_upload_bytes: int = 500 * 1024 * 1024  # 500MB

    asr_model_type: str = "sensevoice"
    asr_model_name: str = "iic/SenseVoiceSmall"

    # Whether the current ASR model needs punc_model (e.g. Paraformer)
    # When False, punc_model is skipped (e.g. SenseVoice, Qwen3-ASR, Fun-ASR-Nano)
    asr_needs_punc: bool = False

    asr_batch_size_s: int = 300
    asr_merge_length_s: float = 15.0
    asr_merge_vad: bool = True
    asr_max_single_segment_time: int = 60000

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096

    ncpu: int = 0

    streaming_asr_enabled: bool = False
    streaming_asr_model_name: str = "paraformer-zh-streaming"

    # Reconnect-resume: suspended-session grace window; liveness timeout while
    # attached is 3x this value (see record.py).
    reconnect_grace_seconds: int = 60

    browser_noise_suppression: bool = True
    audio_source: str = "mic"

    @property
    def upload_dir(self) -> str:
        return os.path.join(self.data_dir, "uploads")

    @property
    def model_cache_dir(self) -> str:
        return os.path.join(self.data_dir, "models")

    @property
    def temp_dir(self) -> str:
        return os.path.join(self.data_dir, "temp")

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "meetingtotext.db")


def coerce_bool(value: Any) -> bool:
    """The one bool coercion rule: bool passes through, strings use .lower()=="true"."""
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def cors_origins_from_env() -> list[str]:
    """Parse ``MTT_CORS_ORIGINS`` into an allowlist.

    Same-origin deployments (nginx reverse-proxy) don't need CORS at all —
    the browser never sends a cross-origin request when frontend and backend
    share one origin.  This list exists for dev cross-origin (vite on
    ``:5173`` proxying to the API on ``:8000``) and explicit multi-origin
    setups.  Configure via ``MTT_CORS_ORIGINS`` as a comma-separated list.

    Returns:
        Stripped, non-empty origins.  Defaults to
        ``["http://localhost:5173", "http://localhost:8000"]`` when the env
        var is unset or blank.
    """
    raw = os.getenv("MTT_CORS_ORIGINS", "")
    if raw.strip() == "":
        return ["http://localhost:5173", "http://localhost:8000"]
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


@dataclass(frozen=True)
class SettingSpec:
    """Single source of truth for one user setting key (Q3(a)).

    models/schemas.py keeps SettingsUpdate/SettingsInfo in sync with the
    SETTING_SPECS registry below; both stay hand-written (no codegen).
    """

    key: str
    caster: Callable[[Any], Any]
    default: Any
    sensitive: bool
    deletable: bool


# Q3(a) write lock — guards EVERY runtime mutation of the `settings` singleton.
#
# Contract: writers serialize on this RLock; readers stay lock-free. Every
# writer performs complete, single `setattr` assignments (never read-modify-
# write of a field), so a lock-free reader on another thread always observes a
# last-committed, fully-formed value. Writers that must touch the singleton
# are: startup.load_user_settings, the settings router POST loop, and the
# DELETE-reset branch. Do NOT add a settings mutation outside this lock.
settings_lock = threading.RLock()

# Defaults snapshot, taken once at import before runtime writes can touch the
# live `settings` singleton. A fresh instance (not the live one) keeps spec
# defaults env-aware, matching the DELETE-reset path (MTT_* boot values remain
# the reset default), and referencing it keeps specs from drifting off the
# Settings class field defaults.
_setting_defaults = Settings()

SETTING_SPECS: dict[str, SettingSpec] = {
    "llm_base_url": SettingSpec(
        "llm_base_url", str, _setting_defaults.llm_base_url, False, True
    ),
    "llm_api_key": SettingSpec(
        "llm_api_key", str, _setting_defaults.llm_api_key, True, True
    ),
    "llm_model": SettingSpec(
        "llm_model", str, _setting_defaults.llm_model, False, True
    ),
    "llm_temperature": SettingSpec(
        "llm_temperature", float, _setting_defaults.llm_temperature, False, True
    ),
    "llm_max_tokens": SettingSpec(
        "llm_max_tokens", int, _setting_defaults.llm_max_tokens, False, True
    ),
    "asr_model_type": SettingSpec(
        "asr_model_type", str, _setting_defaults.asr_model_type, False, True
    ),
    "asr_model_name": SettingSpec(
        "asr_model_name", str, _setting_defaults.asr_model_name, False, True
    ),
    "asr_needs_punc": SettingSpec(
        "asr_needs_punc", coerce_bool, _setting_defaults.asr_needs_punc, False, True
    ),
    "ncpu": SettingSpec("ncpu", int, _setting_defaults.ncpu, False, True),
    "asr_batch_size_s": SettingSpec(
        "asr_batch_size_s", int, _setting_defaults.asr_batch_size_s, False, True
    ),
    "asr_merge_length_s": SettingSpec(
        "asr_merge_length_s", float, _setting_defaults.asr_merge_length_s, False, True
    ),
    "asr_merge_vad": SettingSpec(
        "asr_merge_vad", coerce_bool, _setting_defaults.asr_merge_vad, False, True
    ),
    "asr_max_single_segment_time": SettingSpec(
        "asr_max_single_segment_time",
        int,
        _setting_defaults.asr_max_single_segment_time,
        False,
        True,
    ),
    "streaming_asr_enabled": SettingSpec(
        "streaming_asr_enabled",
        coerce_bool,
        _setting_defaults.streaming_asr_enabled,
        False,
        True,
    ),
    "streaming_asr_model_name": SettingSpec(
        "streaming_asr_model_name",
        str,
        _setting_defaults.streaming_asr_model_name,
        False,
        True,
    ),
    # Metis F11: reconnect_grace_seconds is user-settable (startup loads it) but
    # not deletable — reflected faithfully so DELETE keeps rejecting it.
    "reconnect_grace_seconds": SettingSpec(
        "reconnect_grace_seconds",
        int,
        _setting_defaults.reconnect_grace_seconds,
        False,
        False,
    ),
    "browser_noise_suppression": SettingSpec(
        "browser_noise_suppression",
        coerce_bool,
        _setting_defaults.browser_noise_suppression,
        False,
        True,
    ),
    "audio_source": SettingSpec(
        "audio_source", str, _setting_defaults.audio_source, False, True
    ),
}


settings = Settings()
set_cpu_threads(settings.ncpu)

os.makedirs(settings.data_dir, exist_ok=True)
os.makedirs(settings.upload_dir, exist_ok=True)
os.makedirs(settings.model_cache_dir, exist_ok=True)
os.makedirs(settings.temp_dir, exist_ok=True)
