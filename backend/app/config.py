import os
from pathlib import Path
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


settings = Settings()
set_cpu_threads(settings.ncpu)

os.makedirs(settings.data_dir, exist_ok=True)
os.makedirs(settings.upload_dir, exist_ok=True)
os.makedirs(settings.model_cache_dir, exist_ok=True)
os.makedirs(settings.temp_dir, exist_ok=True)
