"""Hermetic unit tests for backend/app/services/asr_streaming.py (todo 4).

StreamingASRSession had zero coverage. These tests PIN the current resample
math of add_pcm_chunk (asr_streaming.py:33-71) so a later refactor of this
file has a behavioral safety net:

- Single-chunk feeds resample to EXACTLY N * TARGET_SR / input_sr samples
  (N/3 for 48k -> 16k), drained into CHUNK_STRIDE_16K generate() calls.
- RESAMPLE_OVERLAP=256 boundary bookkeeping (:49-57): consecutive chunks
  re-resample the last 256 input samples of the previous chunk for filter
  context and drop the first int(OVERLAP * TARGET_SR / input_sr)=85 output
  samples. Verified both black-box (split vs whole session on a sine whose
  chunk boundary lands on a PEAK, where edge artifacts are maximal) and
  white-box (librosa.resample monkeypatched to record exactly what segment
  was fed and what trim was applied).
- finalize() sends the pending buffer with is_final=True and empties it.
- input at the target rate (16000) takes the identity path (librosa returns
  the input unchanged when orig_sr == target_sr): byte-identical values.
- Guard behavior: empty chunks are a no-op, sample_rate=0 raises
  ZeroDivisionError, negative rates silently never process (pinned as-is;
  a refactor may add validation - update these consciously).

Hermeticity: the model is a recording fake; funasr/modelscope/torch are never
imported. The only third-party calls are numpy and (for one reference
assertion) librosa - the same library the module itself uses.

Numbers pinned here are empirical (librosa 0.10.x / soxr). If a librosa
upgrade changes edge behavior, these tests fail loudly - review and update
the constants deliberately.
"""

import numpy as np
import librosa
import pytest

from backend.app.services import asr_streaming
from backend.app.services.asr_streaming import StreamingASRSession

INPUT_SR = 48000
TARGET_SR = StreamingASRSession.TARGET_SR          # 16000
STRIDE = StreamingASRSession.CHUNK_STRIDE_16K       # 9600 samples at 16kHz
OVERLAP = StreamingASRSession.RESAMPLE_OVERLAP      # 256 input samples
EDGE = 128  # output samples around each chunk seam where edge effects live


class _RecordingModel:
    """Fake streaming-ASR model: records every generate() call, returns scripted results.

    The session reads result[0].get("text", "") and treats any exception as a
    swallowed warning, so script entries are lists of result dicts ([] means
    "no text recognized"). `script` is consumed FIFO; when empty, [] is used.
    """

    def __init__(self):
        self.calls = []
        self.script = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.script.pop(0) if self.script else []


def _pcm16(sig: np.ndarray) -> bytes:
    """int16 mono PCM bytes, the same quantization the session applies."""
    return (sig * 32768.0).astype(np.int16).tobytes()


def _quantized(sig: np.ndarray) -> np.ndarray:
    """Round-trip the signal through int16, matching what add_pcm_chunk sees."""
    return (sig * 32768.0).astype(np.int16).astype(np.float32) / 32768.0


def _feed(session: StreamingASRSession, sig: np.ndarray, chunk_lens) -> None:
    off = 0
    for n in chunk_lens:
        session.add_pcm_chunk(_pcm16(sig[off : off + n]))
        off += n


def _total_resampled(model: _RecordingModel, session: StreamingASRSession) -> np.ndarray:
    """Everything the session produced: drained generate() inputs + pending buffer."""
    parts = [c["input"] for c in model.calls]
    if len(session.resampled_audio):
        parts.append(session.resampled_audio)
    return np.concatenate(parts)


@pytest.mark.parametrize(
    ("n_samples", "expected_leftover"),
    [
        (28800, 0),    # exactly one 16k stride
        (57600, 0),    # exactly two 16k strides
        (30000, 400),  # one stride + 400-sample tail (non-multiple of 3)
    ],
    ids=["one-stride", "two-strides", "one-stride-plus-tail"],
)
def test_single_chunk_resample_length_is_exact_ratio(n_samples, expected_leftover):
    """48k -> 16k resample yields exactly n_samples / 3 output samples."""
    sig = (0.3 * np.sin(2 * np.pi * 997 * np.arange(n_samples) / INPUT_SR)).astype(np.float32)
    model = _RecordingModel()
    session = StreamingASRSession(model, input_sample_rate=INPUT_SR)

    _feed(session, sig, [n_samples])

    expected_total = n_samples * TARGET_SR // INPUT_SR
    assert expected_total == n_samples // 3  # sanity: exact for N divisible by 3
    assert len(session.resampled_audio) == expected_leftover
    assert len(session.resampled_audio) < STRIDE  # drain invariant: pending < stride
    assert [len(c["input"]) for c in model.calls] == [STRIDE] * (expected_total // STRIDE)
    assert sum(len(c["input"]) for c in model.calls) + len(session.resampled_audio) == expected_total


def test_generate_call_kwargs_are_stable():
    """Pin exactly what _process_buffer passes to model.generate (asr_streaming.py:81-88)."""
    n_samples = 28800
    sig = (0.3 * np.sin(2 * np.pi * 997 * np.arange(n_samples) / INPUT_SR)).astype(np.float32)
    model = _RecordingModel()
    session = StreamingASRSession(model, input_sample_rate=INPUT_SR)

    _feed(session, sig, [n_samples])

    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["input"].shape == (STRIDE,)
    assert call["input"].dtype == np.float32
    assert call["cache"] is session.cache            # same dict object, mutated across calls
    assert call["is_final"] is False
    assert call["chunk_size"] == StreamingASRSession.CHUNK_SIZE
    assert call["encoder_chunk_look_back"] == 4
    assert call["decoder_chunk_look_back"] == 1


def test_single_chunk_matches_direct_librosa_resample():
    """The session's resample IS librosa.resample of the quantized raw audio (bit-identical)."""
    n_samples = 57600
    sig = (0.3 * np.sin(2 * np.pi * 997 * np.arange(n_samples) / INPUT_SR)).astype(np.float32)
    model = _RecordingModel()
    session = StreamingASRSession(model, input_sample_rate=INPUT_SR)

    _feed(session, sig, [n_samples])

    reference = librosa.resample(_quantized(sig), orig_sr=INPUT_SR, target_sr=TARGET_SR)
    assert len(reference) == n_samples // 3
    assert len(model.calls) == 2
    assert np.array_equal(model.calls[0]["input"], reference[:STRIDE])
    assert np.array_equal(model.calls[1]["input"], reference[STRIDE:])


def test_split_vs_whole_overlap_continuity():
    """Chunking the same input must not change the resampled stream beyond pinned bounds.

    The input sine uses frequency 2005/12 Hz so the chunk boundary (input
    sample 28800) lands exactly on a PEAK: any hard cut / missing filter
    context there produces the largest possible seam artifact. Measured
    behavior being pinned (see module docstring):

    * segment interiors reproduce a single big resample to float noise (1e-4);
    * the tail of each segment carries a bounded edge transient (no FUTURE
      context exists at resample time) - 0.05;
    * the head of the FOLLOWING segment is protected by RESAMPLE_OVERLAP:
      0.03 here, versus ~0.17 if the overlap were removed;
    * overlap_out = int(256 * 16000 / 48000) = 85 truncates 85.333, so each
      boundary advances the stream by +1/3 output sample: total length drifts
      by at most one sample per boundary (empirically +1, one leftover sample).
    """
    freq = 2005.0 / 12.0
    n_samples = 57600
    seam_input = 28800  # input index of the chunk boundary
    # Document why this frequency: sin phase at the seam is pi/2 -> peak.
    assert np.abs(np.sin(2 * np.pi * freq * seam_input / INPUT_SR)) == pytest.approx(1.0, abs=1e-6)

    sig = (0.5 * np.sin(2 * np.pi * freq * np.arange(n_samples) / INPUT_SR)).astype(np.float32)

    whole_model, split_model = _RecordingModel(), _RecordingModel()
    whole = StreamingASRSession(whole_model, input_sample_rate=INPUT_SR)
    split = StreamingASRSession(split_model, input_sample_rate=INPUT_SR)
    _feed(whole, sig, [n_samples])
    _feed(split, sig, [seam_input, n_samples - seam_input])

    whole_stream = _total_resampled(whole_model, whole)
    split_stream = _total_resampled(split_model, split)

    # Same drain structure on both sides: two full strides.
    assert [len(c["input"]) for c in whole_model.calls] == [STRIDE, STRIDE]
    assert [len(c["input"]) for c in split_model.calls] == [STRIDE, STRIDE]

    # Drift pin: at most one extra output sample per chunk boundary.
    drift = len(split_stream) - len(whole_stream)
    assert drift in (0, 1)
    assert 0 <= len(split.resampled_audio) <= 1  # empirically: 1 leftover sample

    seg1, seg2 = split_stream[:STRIDE], split_stream[STRIDE : 2 * STRIDE]
    # Interior of the first segment: identical to the single big resample.
    assert np.allclose(seg1[: STRIDE - EDGE], whole_stream[: STRIDE - EDGE], atol=1e-4)
    # Tail of segment 1: inherent edge transient, bounded (no future context).
    assert np.allclose(seg1[STRIDE - EDGE :], whole_stream[STRIDE - EDGE : STRIDE], atol=0.05)
    # Head of segment 2: the overlap re-resample keeps the seam continuous.
    assert np.allclose(seg2[:EDGE], whole_stream[STRIDE : STRIDE + EDGE], atol=0.03)
    # Body and tail of segment 2: only the sub-sample phase drift remains.
    assert np.allclose(seg2[EDGE : STRIDE - EDGE],
                       whole_stream[STRIDE + EDGE : 2 * STRIDE - EDGE], atol=0.04)
    assert np.allclose(seg2[STRIDE - EDGE :], whole_stream[2 * STRIDE - EDGE :], atol=0.04)


def test_overlap_resample_bookkeeping_whitebox(monkeypatch):
    """Pin the :49-57 bookkeeping exactly: what segment is re-resampled, what is dropped.

    librosa.resample is replaced by a recording fake, so the assertions do not
    depend on any resampler implementation at all.
    """
    class _FakeResample:
        def __init__(self):
            self.segments = []
            self.outputs = []

        def __call__(self, seg, orig_sr, target_sr):
            assert orig_sr == INPUT_SR and target_sr == TARGET_SR
            self.segments.append(seg.copy())
            out = np.arange(len(seg) * target_sr // orig_sr, dtype=np.float32) + 0.25
            self.outputs.append(out)
            return out

    fake = _FakeResample()
    monkeypatch.setattr(asr_streaming.librosa, "resample", fake)

    n_samples = 57600
    chunk = 28800
    ramp = np.linspace(-1.0, 1.0, n_samples, dtype=np.float32)
    model = _RecordingModel()
    session = StreamingASRSession(model, input_sample_rate=INPUT_SR)
    _feed(session, ramp, [chunk, chunk])

    q = _quantized(ramp)
    assert len(fake.segments) == 2
    # First chunk: whole raw audio, resampled without any overlap trim
    # (_processed_input == 0 < RESAMPLE_OVERLAP).
    assert np.array_equal(fake.segments[0], q[:chunk])
    assert np.array_equal(model.calls[0]["input"], fake.outputs[0])
    # Second chunk: raw audio has been trimmed to the last OVERLAP input
    # samples, so the segment handed to the resampler is exactly
    # [chunk - OVERLAP : chunk] ++ new chunk.
    assert len(fake.segments[1]) == OVERLAP + chunk
    assert np.array_equal(fake.segments[1], np.concatenate([q[chunk - OVERLAP : chunk], q[chunk:]]))

    overlap_out = int(OVERLAP * TARGET_SR / INPUT_SR)  # the code's own formula
    assert overlap_out == 85
    # The first overlap_out resampled samples are dropped to avoid duplicating
    # the overlap region in the output stream.
    assert np.array_equal(model.calls[1]["input"], fake.outputs[1][overlap_out:])
    assert len(model.calls[1]["input"]) == len(fake.outputs[1]) - overlap_out == STRIDE


def test_finalize_drains_pending_buffer():
    """finalize() flushes whatever is left (< stride) with is_final=True and empties it."""
    n_samples = 30000
    sig = (0.3 * np.sin(2 * np.pi * 440 * np.arange(n_samples) / INPUT_SR)).astype(np.float32)
    model = _RecordingModel()
    session = StreamingASRSession(model, input_sample_rate=INPUT_SR)

    _feed(session, sig, [n_samples])

    assert len(model.calls) == 1                       # streaming call drained 9600
    assert len(session.resampled_audio) == 400         # pending tail < stride
    pending = session.resampled_audio.copy()

    result = session.finalize()

    assert len(model.calls) == 2
    final_call = model.calls[1]
    assert final_call["is_final"] is True
    assert final_call["cache"] is session.cache
    assert final_call["chunk_size"] == StreamingASRSession.CHUNK_SIZE
    assert np.array_equal(final_call["input"], pending)  # exactly the pending tail
    assert result == ""                                  # fake recognized no text
    assert len(session.resampled_audio) == 0
    assert session.resampled_audio.dtype == np.float32

    # A second finalize with an empty buffer must NOT call generate again.
    assert session.finalize() == ""
    assert len(model.calls) == 2


def test_finalize_appends_text_to_partial():
    """Recognized text accumulates into partial_text across streaming and final calls."""
    n_samples = 30000
    sig = (0.3 * np.sin(2 * np.pi * 440 * np.arange(n_samples) / INPUT_SR)).astype(np.float32)
    model = _RecordingModel()
    model.script = [[{"text": "第一"}], [{"text": "第二"}]]
    session = StreamingASRSession(model, input_sample_rate=INPUT_SR)

    streaming_text = _feed_return(session, sig, [n_samples])

    assert streaming_text == "第一"
    assert session.partial_text == "第一"
    assert session.finalize() == "第一第二"


def _feed_return(session, sig, chunk_lens):
    """Feed chunks and return the concatenation of add_pcm_chunk return values."""
    texts = []
    off = 0
    for n in chunk_lens:
        texts.append(session.add_pcm_chunk(_pcm16(sig[off : off + n])))
        off += n
    return "".join(texts)


def test_passthrough_when_input_rate_equals_target():
    """16kHz input takes the identity path: values pass through untouched (no artifacts)."""
    rng = np.random.default_rng(7)
    noise = rng.uniform(-0.5, 0.5, 28800).astype(np.float32)
    expected = _quantized(noise)

    # Single chunk: 3 full strides, drained in order.
    model = _RecordingModel()
    session = StreamingASRSession(model, input_sample_rate=TARGET_SR)
    _feed(session, noise, [28800])
    assert [len(c["input"]) for c in model.calls] == [STRIDE, STRIDE, STRIDE]
    assert len(session.resampled_audio) == 0
    for i, call in enumerate(model.calls):
        assert call["input"].dtype == np.float32
        assert np.array_equal(call["input"], expected[i * STRIDE : (i + 1) * STRIDE])

    # Split feed: the seam must not duplicate or drop a single sample. White
    # noise guarantees any shift by even one sample breaks array_equal.
    model2 = _RecordingModel()
    session2 = StreamingASRSession(model2, input_sample_rate=TARGET_SR)
    _feed(session2, noise, [14400, 14400])
    assert [len(c["input"]) for c in model2.calls] == [STRIDE, STRIDE, STRIDE]
    assert np.array_equal(model2.calls[0]["input"], expected[0:STRIDE])
    assert np.array_equal(model2.calls[1]["input"], expected[STRIDE : 2 * STRIDE])
    assert np.array_equal(model2.calls[2]["input"], expected[2 * STRIDE : 3 * STRIDE])
    assert len(session2.resampled_audio) == 0


def test_empty_chunk_is_a_noop():
    """Empty chunks change nothing: no crash, no state, no generate() call."""
    model = _RecordingModel()
    session = StreamingASRSession(model, input_sample_rate=INPUT_SR)

    assert session.add_pcm_chunk(b"") == ""
    assert len(model.calls) == 0
    assert len(session.raw_audio) == 0
    assert len(session.resampled_audio) == 0
    assert session._processed_input == 0
    assert session.partial_text == ""

    # The session must remain fully usable afterwards.
    sig = (0.3 * np.sin(2 * np.pi * 440 * np.arange(28800) / INPUT_SR)).astype(np.float32)
    _feed(session, sig, [28800])
    assert len(model.calls) == 1


def test_zero_input_rate_raises():
    """sample_rate=0 currently raises ZeroDivisionError inside the ratio math.

    This is a PIN of current behavior, not an endorsement: a later refactor
    may validate input_sample_rate and raise a ValueError instead. If that
    happens, update this test in the same commit.
    """
    session = StreamingASRSession(_RecordingModel(), input_sample_rate=0)
    chunk = np.zeros(100, dtype=np.int16).tobytes()
    with pytest.raises(ZeroDivisionError):
        session.add_pcm_chunk(chunk)


def test_negative_input_rate_never_processes():
    """A negative rate makes est_new_16k negative, so no resample ever triggers.

    Current behavior: add_pcm_chunk silently returns "" forever. Pinned as-is
    so a refactor that adds input validation changes this test consciously.
    """
    model = _RecordingModel()
    session = StreamingASRSession(model, input_sample_rate=-16000)
    chunk = np.zeros(100, dtype=np.int16).tobytes()

    assert session.add_pcm_chunk(chunk) == ""
    assert len(model.calls) == 0
    assert len(session.resampled_audio) == 0
    assert len(session.raw_audio) == 100  # raw audio still accumulates


def test_result_without_text_key_is_tolerated():
    """A generate() result whose first dict lacks 'text' contributes nothing, no crash.

    Pins the result[0].get("text", "") guard in _process_buffer (:89-90).
    """
    n_samples = 28800
    sig = (0.3 * np.sin(2 * np.pi * 440 * np.arange(n_samples) / INPUT_SR)).astype(np.float32)
    model = _RecordingModel()
    model.script = [[{}]]  # dict without "text" key
    session = StreamingASRSession(model, input_sample_rate=INPUT_SR)

    assert _feed_return(session, sig, [n_samples]) == ""
    assert session.partial_text == ""
