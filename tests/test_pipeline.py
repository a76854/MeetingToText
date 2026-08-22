import sys
import os
from pathlib import Path

import pytest

# Non-hermetic: downloads FunASR models; skip by default, run via `pytest -m smoke`.
pytestmark = pytest.mark.smoke


@pytest.fixture(scope="module", autouse=True)
def setup_path():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _list_recordings():
    upload_dir = Path(__file__).resolve().parent.parent / "data" / "uploads"
    return sorted(upload_dir.glob("*.wav"), key=os.path.getmtime, reverse=True)


def _find_speech_file():
    from funasr import AutoModel
    model = None
    try:
        model = AutoModel(
            model="iic/SenseVoiceSmall",
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 60000},
            spk_model="cam++",
        )
        for f in _list_recordings():
            result = model.generate(input=str(f), cache={}, language="auto",
                                    use_itn=True, batch_size_s=60, merge_vad=True, merge_length_s=15)
            text = result[0].get("text", "")
            if text and text.strip() and "empty speech" not in str(result).lower():
                import soundfile as sf
                info = sf.info(str(f))
                return str(f), info.duration, info.samplerate
    except Exception:
        pass
    return None, 0, 0


def test_audio_files_exist():
    files = _list_recordings()
    if not files:
        pytest.skip("No recorded files found")

    import soundfile as sf
    from funasr import AutoModel

    model = AutoModel(
        model="iic/SenseVoiceSmall",
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 60000},
        spk_model="cam++",
    )

    for f in files:
        info = sf.info(str(f))
        result = model.generate(input=str(f), cache={}, language="auto",
                                use_itn=True, batch_size_s=60, merge_vad=True, merge_length_s=15)
        text = result[0].get("text", "")
        has_speech = bool(text and text.strip() and not text.startswith("<|"))
        print(f"  {f.name}  {info.duration:.1f}s  {'HAS_SPEECH' if has_speech else 'SILENT'}")

    assert any(
        bool(r[0].get("text", "").strip()) for f in files
        for r in [model.generate(input=str(f), cache={}, language="auto",
                                  use_itn=True, batch_size_s=60, merge_vad=True, merge_length_s=15)]
    ), "All recordings are silent. Check microphone input."


def test_audio_file_properties():
    files = _list_recordings()
    if not files:
        pytest.skip("No recorded files found")

    import soundfile as sf

    for f in files:
        info = sf.info(str(f))
        data, sr = sf.read(str(f))
        max_amp = abs(data).max() if len(data) > 0 else 0
        rms = (data ** 2).mean() ** 0.5 if len(data) > 0 else 0

        issues = []
        if max_amp >= 0.99:
            issues.append("CLIPPING (max >= 0.99)")
        if rms < 0.001:
            issues.append("NEAR_SILENCE")
        if info.samplerate != 16000:
            issues.append(f"BAD_SR={info.samplerate}")

        status = " | ".join(issues) if issues else "OK"
        print(f"  {f.name}  {info.duration:.1f}s  max={max_amp:.4f}  rms={rms:.6f}  [{status}]")


def test_asr_service():
    from backend.app.services.asr import create_asr

    speech_file, dur, sr = _find_speech_file()
    if not speech_file:
        pytest.skip("No recording with speech found — check microphone input")

    print(f"\n  Testing with: {Path(speech_file).name} ({dur:.1f}s, {sr}Hz)")

    asr = create_asr("sensevoice")
    assert asr is not None

    import time
    t0 = time.time()
    segments = asr.transcribe(speech_file, language="auto")
    elapsed = time.time() - t0
    print(f"  ASR took {elapsed:.1f}s")
    print(f"  Segments: {len(segments)}")

    assert isinstance(segments, list)

    for seg in segments[:5]:
        spk = seg.get("speaker", "?")
        txt = seg.get("text", "")
        print(f"    [{spk}] {seg['start']:.1f}s-{seg['end']:.1f}s: {txt}")

    has_text = any(s.get("text", "").strip() for s in segments)
    if not has_text:
        print("  WARNING: Segments exist but all have empty text. Audio quality may be poor.")
    else:
        print("  Text extraction OK")


def test_full_pipeline():
    from backend.app.services.pipeline import create_task, run_pipeline, get_task

    speech_file, dur, sr = _find_speech_file()
    if not speech_file:
        pytest.skip("No recording with speech found — check microphone input")

    print(f"\n  Pipeline input: {Path(speech_file).name} ({dur:.1f}s)")

    task = create_task(filename=Path(speech_file).name, audio_path=speech_file)
    print(f"  Task created: {task.id}")

    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_pipeline(task.id))
    finally:
        loop.close()

    task = get_task(task.id)
    assert task is not None

    print(f"  Status: {task.status.value}")

    if task.status.value == "error":
        pytest.fail(f"Pipeline failed: {task.error}")

    if task.status.value == "done":
        assert task.result is not None
        print(f"  Duration: {task.result.duration:.1f}s")
        print(f"  Segments: {len(task.result.segments)}")
        print(f"  Full text preview: {task.result.full_text[:200]}")
        for seg in task.result.segments[:3]:
            print(f"    [{seg.speaker}] {seg.start:.1f}s-{seg.end:.1f}s: {seg.text}")
    else:
        pytest.fail(f"Task not done: {task.status.value}")
