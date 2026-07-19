import os
from pathlib import Path
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
os.environ.setdefault("MODELSCOPE_CACHE", os.path.join(DATA_DIR, "models"))


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

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096

    streaming_asr_enabled: bool = False
    streaming_asr_model_name: str = "paraformer-zh-streaming"

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

os.makedirs(settings.data_dir, exist_ok=True)
os.makedirs(settings.upload_dir, exist_ok=True)
os.makedirs(settings.model_cache_dir, exist_ok=True)
os.makedirs(settings.temp_dir, exist_ok=True)
