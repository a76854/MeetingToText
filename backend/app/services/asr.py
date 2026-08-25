import os
import threading
from abc import ABC, abstractmethod
from typing import Any

from backend.app.services.asr_parse import parse_result
from backend.app.services.asr_patch import apply_funasr_distribute_spk_patch


def _resolve_ncpu(setting: int | None) -> int:
    max_ncpu = os.cpu_count() or 4
    if setting is None or setting < 1:
        return max_ncpu
    return min(setting, max_ncpu)


# Patch must be applied at import time, before any engine loads a FunASR model.
apply_funasr_distribute_spk_patch()


class BaseASR(ABC):
    model: Any = None

    @abstractmethod
    def load_model(self):
        ...

    def _transcribe_with_funasr(self, audio_path: str, language: str) -> list[dict]:
        if self.model is None:
            self.load_model()
        from backend.app.config import settings
        result = self.model.generate(
            input=audio_path,
            cache={},
            language=language,
            use_itn=True,
            batch_size_s=settings.asr_batch_size_s,
            merge_vad=settings.asr_merge_vad,
            merge_length_s=settings.asr_merge_length_s,
        )
        return parse_result(result)

    @abstractmethod
    def transcribe(self, audio_path: str, language: str = "zh") -> list[dict]:
        ...

    @abstractmethod
    def unload(self):
        ...


class SenseVoiceASR(BaseASR):
    def __init__(self, model_name: str = "iic/SenseVoiceSmall", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None

    def load_model(self):
        from funasr import AutoModel

        from backend.app.config import settings
        kwargs: dict = dict(
            model=self.model_name,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": settings.asr_max_single_segment_time},
            spk_model="cam++",
            device=self.device,
            disable_update=True,
            ncpu=_resolve_ncpu(settings.ncpu),
        )
        if settings.asr_needs_punc:
            kwargs["punc_model"] = "ct-punc"
        self.model = AutoModel(**kwargs)

    def transcribe(self, audio_path: str, language: str = "auto") -> list[dict]:
        return self._transcribe_with_funasr(audio_path, language)

    def unload(self):
        self.model = None


class ParaformerASR(BaseASR):
    def __init__(
        self,
        model_name: str = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",  # noqa: E501
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.device = device
        self.model = None

    def load_model(self):
        from funasr import AutoModel

        from backend.app.config import settings
        self.model = AutoModel(
            model=self.model_name,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": settings.asr_max_single_segment_time},
            spk_model="cam++",
            punc_model="ct-punc",
            device=self.device,
            ncpu=_resolve_ncpu(settings.ncpu),
        )

    def transcribe(self, audio_path: str, language: str = "zh") -> list[dict]:
        return self._transcribe_with_funasr(audio_path, language)

    def unload(self):
        self.model = None


asr_registry: dict[str, type[BaseASR]] = {
    "sensevoice": SenseVoiceASR,
    "paraformer": ParaformerASR,
}


def create_asr(model_type: str, model_name: str | None = None) -> BaseASR:
    cls = asr_registry.get(model_type)
    if cls is None:
        raise ValueError(
            f"Unknown ASR model type: {model_type}. Available: {list(asr_registry.keys())}"
        )
    kwargs = {}
    if model_name:
        kwargs["model_name"] = model_name
    return cls(**kwargs)


_asr_cache: dict[str, BaseASR] = {}
_asr_lock = threading.Lock()


def get_asr(model_type: str, model_name: str | None = None) -> BaseASR:
    key = f"{model_type}:{model_name or ''}"
    engine = _asr_cache.get(key)
    if engine is not None:
        return engine
    with _asr_lock:
        engine = _asr_cache.get(key)
        if engine is not None:
            return engine
        engine = create_asr(model_type, model_name)
        engine.load_model()
        _asr_cache[key] = engine
        return engine


def unload_all_asr() -> None:
    with _asr_lock:
        for engine in _asr_cache.values():
            engine.unload()
        _asr_cache.clear()
