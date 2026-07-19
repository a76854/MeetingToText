from abc import ABC, abstractmethod
from typing import Optional


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
        segments = []
        if isinstance(result, list) and len(result) > 0:
            item = result[0]
            for sent in item.get("sentence_info", []):
                segments.append({
                    "speaker": sent.get("spk", ""),
                    "text": sent.get("text", ""),
                    "start": float(sent.get("start", 0)) / 1000.0,
                    "end": float(sent.get("end", 0)) / 1000.0,
                })
        if not segments:
            texts = item.get("text", "")
            if isinstance(texts, str):
                texts = [texts]
            timestamps = item.get("timestamp", [])
            if isinstance(timestamps, list) and timestamps:
                for i, ts in enumerate(timestamps):
                    if isinstance(ts, list) and len(ts) == 2:
                        segments.append({
                            "speaker": "",
                            "text": texts[i] if i < len(texts) else "",
                            "start": float(ts[0]) / 1000.0,
                            "end": float(ts[1]) / 1000.0,
                        })
        return segments

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
        segments = []
        if isinstance(result, list) and len(result) > 0:
            item = result[0]
            for sent in item.get("sentence_info", []):
                segments.append({
                    "speaker": sent.get("spk", ""),
                    "text": sent.get("text", ""),
                    "start": float(sent.get("start", 0)) / 1000.0,
                    "end": float(sent.get("end", 0)) / 1000.0,
                })
        if not segments:
            texts = item.get("text", "")
            if isinstance(texts, str):
                texts = [texts]
            timestamps = item.get("timestamp", [])
            if isinstance(timestamps, list) and timestamps:
                for i, ts in enumerate(timestamps):
                    if isinstance(ts, list) and len(ts) == 2:
                        segments.append({
                            "speaker": "",
                            "text": texts[i] if i < len(texts) else "",
                            "start": float(ts[0]) / 1000.0,
                            "end": float(ts[1]) / 1000.0,
                        })
        return segments

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
