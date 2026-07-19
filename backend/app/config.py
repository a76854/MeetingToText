import os
from pathlib import Path
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    data_dir: str = os.path.join(Path.home(), ".meetingtotext")
    upload_dir: str = os.path.join(Path.home(), ".meetingtotext", "uploads")
    model_cache_dir: str = os.path.join(Path.home(), ".meetingtotext", "models")
    temp_dir: str = os.path.join(Path.home(), ".meetingtotext", "temp")

    asr_model_type: str = "sensevoice"
    asr_model_name: str = "iic/SenseVoiceSmall"

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096

    target_sr: int = 16000

    class Config:
        env_prefix = "MTT_"
        env_file = os.path.join(PROJECT_ROOT, ".env")
        env_file_encoding = "utf-8"


settings = Settings()

os.makedirs(settings.data_dir, exist_ok=True)
os.makedirs(settings.upload_dir, exist_ok=True)
os.makedirs(settings.model_cache_dir, exist_ok=True)
os.makedirs(settings.temp_dir, exist_ok=True)
