from abc import ABC, abstractmethod
from typing import Optional
import re
import threading


def _clean_text(text: str) -> str:
    text = re.sub(r'<\|[^|>]+\|>', '', text)
    text = text.strip()
    text = re.sub(r'^[。，、；：！？,.!?:;]+', '', text)
    text = text.strip()
    return text


def _parse_result(result: list) -> list[dict]:
    segments = []
    if not (isinstance(result, list) and result):
        return segments

    item = result[0]
    for sent in item.get("sentence_info", []):
        text = _clean_text(sent.get("text", ""))
        if not text:
            continue
        start = sent.get("start") or 0
        end = sent.get("end") or 0
        segments.append({
            "speaker": sent.get("spk", ""),
            "text": text,
            "start": float(start) / 1000.0,
            "end": float(end) / 1000.0,
        })

    if not segments:
        raw_text = item.get("text", "")
        if isinstance(raw_text, str):
            raw_text = _clean_text(raw_text)
        timestamps = item.get("timestamp", [])
        if raw_text and isinstance(timestamps, list) and timestamps:
            texts = raw_text if isinstance(raw_text, list) else [raw_text]
            for i, ts in enumerate(timestamps):
                if isinstance(ts, list) and len(ts) == 2:
                    txt = texts[i] if i < len(texts) else ""
                    if not txt:
                        continue
                    segments.append({
                        "speaker": "",
                        "text": txt,
                        "start": float(ts[0] or 0) / 1000.0,
                        "end": float(ts[1] or 0) / 1000.0,
                    })

    return segments


class BaseASR(ABC):
    @abstractmethod
    def load_model(self):
        ...

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
        self.model = AutoModel(
            model=self.model_name,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 60000},
            spk_model="cam++",
            device=self.device,
            disable_update=True,
        )

    def transcribe(self, audio_path: str, language: str = "auto") -> list[dict]:
        if self.model is None:
            self.load_model()
        result = self.model.generate(
            input=audio_path,
            cache={},
            language=language,
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
        )
        return _parse_result(result)

    def unload(self):
        self.model = None


class ParaformerASR(BaseASR):
    def __init__(self, model_name: str = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None

    def load_model(self):
        from funasr import AutoModel
        self.model = AutoModel(
            model=self.model_name,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 60000},
            spk_model="cam++",
            punc_model="ct-punc",
            device=self.device,
        )

    def transcribe(self, audio_path: str, language: str = "zh") -> list[dict]:
        if self.model is None:
            self.load_model()
        result = self.model.generate(
            input=audio_path,
            cache={},
            language=language,
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
        )
        return _parse_result(result)

    def unload(self):
        self.model = None


asr_registry: dict[str, type[BaseASR]] = {
    "sensevoice": SenseVoiceASR,
    "paraformer": ParaformerASR,
}


def create_asr(model_type: str, model_name: Optional[str] = None) -> BaseASR:
    cls = asr_registry.get(model_type)
    if cls is None:
        raise ValueError(f"Unknown ASR model type: {model_type}. Available: {list(asr_registry.keys())}")
    kwargs = {}
    if model_name:
        kwargs["model_name"] = model_name
    return cls(**kwargs)


_asr_cache: dict[str, BaseASR] = {}
_asr_lock = threading.Lock()


def get_asr(model_type: str, model_name: Optional[str] = None) -> BaseASR:
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
