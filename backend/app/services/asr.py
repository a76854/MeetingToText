import os
from abc import ABC, abstractmethod
from typing import Optional
import re
import threading


def _resolve_ncpu(setting: int | None) -> int:
    max_ncpu = os.cpu_count() or 4
    if setting is None or setting < 1:
        return max_ncpu
    return min(setting, max_ncpu)


def _patch_funasr_distribute_spk() -> None:
    try:
        import funasr.models.campplus.utils as _utils
    except Exception:
        return
    if getattr(_utils.distribute_spk, "_mt_patched", False):
        return

    def _safe_distribute_spk(sentence_list, sd_time_list):
        cleaned = []
        for entry in sd_time_list:
            if not entry:
                continue
            st, ed, spk = entry[0], entry[1], entry[2] if len(entry) > 2 else 0
            if st is None or ed is None:
                continue
            cleaned.append((float(st) * 1000.0, float(ed) * 1000.0, spk))

        if not cleaned:
            for d in sentence_list:
                d["spk"] = 0
            return sentence_list

        for d in sentence_list:
            sentence_start = d.get("start")
            sentence_end = d.get("end")
            if sentence_start is None or sentence_end is None:
                d["spk"] = 0
                continue
            sentence_spk = 0
            max_overlap = 0
            for spk_st, spk_ed, spk in cleaned:
                try:
                    overlap = max(min(sentence_end, spk_ed) - max(sentence_start, spk_st), 0)
                except TypeError:
                    continue
                if overlap > max_overlap:
                    max_overlap = overlap
                    sentence_spk = spk
            d["spk"] = int(sentence_spk)
        return sentence_list

    _safe_distribute_spk._mt_patched = True
    _utils.distribute_spk = _safe_distribute_spk
    try:
        import funasr.auto.auto_model as _am
        _am.distribute_spk = _safe_distribute_spk
    except Exception:
        pass


_patch_funasr_distribute_spk()


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
        spk = sent.get("spk", "")
        if spk is not None and spk != "":
            spk = f"说话人{int(spk) + 1}"
        else:
            spk = ""
        segments.append({
            "speaker": spk,
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
        from backend.app.config import settings
        self.model = AutoModel(
            model=self.model_name,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 60000},
            spk_model="cam++",
            punc_model="ct-punc",
            device=self.device,
            disable_update=True,
            ncpu=_resolve_ncpu(settings.ncpu),
        )

    def transcribe(self, audio_path: str, language: str = "auto") -> list[dict]:
        if self.model is None:
            self.load_model()
        result = self.model.generate(
            input=audio_path,
            cache={},
            language=language,
            use_itn=True,
            batch_size_s=300,
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
        from backend.app.config import settings
        self.model = AutoModel(
            model=self.model_name,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 60000},
            spk_model="cam++",
            punc_model="ct-punc",
            device=self.device,
            ncpu=_resolve_ncpu(settings.ncpu),
        )

    def transcribe(self, audio_path: str, language: str = "zh") -> list[dict]:
        if self.model is None:
            self.load_model()
        result = self.model.generate(
            input=audio_path,
            cache={},
            language=language,
            use_itn=True,
            batch_size_s=300,
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
