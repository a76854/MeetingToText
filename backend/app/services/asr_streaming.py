import threading
import logging
import numpy as np
import librosa

logger = logging.getLogger(__name__)


class StreamingASRSession:
    """Server-side streaming ASR session for one recording.

    Accumulates raw PCM chunks (int16, mono), resamples to 16kHz, and feeds
    fixed-size chunks to FunASR paraformer-zh-streaming model.
    """

    # chunk_size = [0, 10, 5] -> 10*960 = 9600 samples = 600ms at 16kHz
    CHUNK_SIZE = [0, 10, 5]
    CHUNK_STRIDE_16K = CHUNK_SIZE[1] * 960  # 9600 samples
    TARGET_SR = 16000

    def __init__(self, model, input_sample_rate: int):
        self.model = model
        self.input_sr = input_sample_rate
        self.cache = {}
        self.raw_audio = np.array([], dtype=np.float32)
        self.resampled_audio = np.array([], dtype=np.float32)
        self.partial_text = ""
        self._processed_16k = 0

    def add_pcm_chunk(self, chunk: bytes) -> str:
        """Add a chunk of int16 mono PCM. Return newly recognized text (may be empty)."""
        if not chunk:
            return ""
        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) == 0:
            return ""
        self.raw_audio = np.concatenate([self.raw_audio, samples])

        # Only resample when we have enough new audio to process at least one chunk
        target_16k_len = int(len(self.raw_audio) * self.TARGET_SR / self.input_sr)
        if target_16k_len - self._processed_16k < self.CHUNK_STRIDE_16K:
            return ""

        # Resample everything we have so far
        new_resampled = librosa.resample(
            self.raw_audio, orig_sr=self.input_sr, target_sr=self.TARGET_SR
        )
        # Append only the newly available portion beyond what we've already processed
        if len(new_resampled) > self._processed_16k:
            self.resampled_audio = np.concatenate([
                self.resampled_audio,
                new_resampled[self._processed_16k:],
            ])
        else:
            # Resampled output is shorter than expected (rare), just use what's there
            self.resampled_audio = new_resampled
        self._processed_16k = len(new_resampled)

        return self._process_buffer()

    def _process_buffer(self) -> str:
        """Consume resampled audio in CHUNK_STRIDE_16K chunks and run streaming ASR."""
        new_text = ""
        while len(self.resampled_audio) >= self.CHUNK_STRIDE_16K:
            chunk = self.resampled_audio[:self.CHUNK_STRIDE_16K]
            self.resampled_audio = self.resampled_audio[self.CHUNK_STRIDE_16K:]

            try:
                result = self.model.generate(
                    input=chunk,
                    cache=self.cache,
                    is_final=False,
                    chunk_size=self.CHUNK_SIZE,
                    encoder_chunk_look_back=4,
                    decoder_chunk_look_back=1,
                )
                if result and len(result) > 0:
                    text = result[0].get("text", "")
                    if text:
                        new_text += text
                        self.partial_text += text
            except Exception:
                # Swallow streaming errors to avoid breaking the recording
                pass

        return new_text

    def finalize(self) -> str:
        """Process any remaining audio with is_final=True."""
        if len(self.resampled_audio) == 0:
            return self.partial_text

        try:
            result = self.model.generate(
                input=self.resampled_audio,
                cache=self.cache,
                is_final=True,
                chunk_size=self.CHUNK_SIZE,
                encoder_chunk_look_back=4,
                decoder_chunk_look_back=1,
            )
            if result and len(result) > 0:
                text = result[0].get("text", "")
                if text:
                    self.partial_text += text
        except Exception:
            pass

        self.resampled_audio = np.array([], dtype=np.float32)
        return self.partial_text


class StreamingASR:
    """Lazy singleton for the streaming ASR model."""

    _instance: "StreamingASR | None" = None
    _lock = threading.Lock()

    def __init__(self, model_name: str = "paraformer-zh-streaming", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self._load_lock = threading.Lock()

    @classmethod
    def get_instance(cls, model_name: str = "paraformer-zh-streaming", device: str = "cpu") -> "StreamingASR":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(model_name, device)
        return cls._instance

    def load(self):
        with self._load_lock:
            if self.model is None:
                from funasr import AutoModel
                logger.info(f"Loading model {self.model_name} ...")
                self.model = AutoModel(
                    model=self.model_name,
                    device=self.device,
                )
                logger.info(f"Model {self.model_name} loaded")
        return self.model

    def create_session(self, input_sample_rate: int) -> StreamingASRSession:
        return StreamingASRSession(self.load(), input_sample_rate)

    def unload(self):
        self.model = None

    @classmethod
    def unload_all(cls):
        with cls._lock:
            if cls._instance:
                cls._instance.unload()
            cls._instance = None
