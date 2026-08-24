"""Pure parsing helpers for FunASR model output.

FunASR's ``AutoModel.generate`` returns different result shapes depending on
model type and runtime kwargs. This module normalises them into the canonical
segment dict ``{"speaker": str, "text": str, "start": float, "end": float}``
where start/end are seconds from audio begin.

Two shapes are handled by ``parse_result``:

1. **Sentence-info shape** (SenseVoice / Paraformer with VAD + CAM++ speaker
   diarisation): the first result item carries a ``sentence_info`` list of
   dicts, each with ``text`` (or ``sentence``), ``start``/``end`` in
   milliseconds and an optional ``spk`` id. CAM++ speaker ids are 0-based;
   they are rendered into the human label ``说话人N`` (1-based) via
   ``SPEAKER_LABEL_TEMPLATE``.
2. **Raw text + timestamp fallback**: when sentence info produced no segment
   (e.g. short utterance or models returning flat output), the item's
   ``text`` and ``timestamp`` (list of ``[start_ms, end_ms]`` pairs) are used
   directly. These segments carry no speaker label.

Both shapes report times in milliseconds; they are converted to seconds via
``MS_PER_S``.
"""

import logging
import re

logger = logging.getLogger(__name__)

MS_PER_S = 1000.0
SPEAKER_LABEL_TEMPLATE = "说话人{}"


def clean_text(text: str) -> str:
    text = re.sub(r'<\|[^|>]+\|>', '', text)
    text = text.strip()
    text = re.sub(r'^[。，、；：！？,.!?:;]+', '', text)
    text = text.strip()
    return text


def parse_result(result: list) -> list[dict]:
    segments = []
    if not (isinstance(result, list) and result):
        return segments

    item = result[0]
    logger.info(f"_parse_result: keys={list(item.keys())} text_len={len(str(item.get('text','')))}, si_count={len(item.get('sentence_info', []))}")

    for i, sent in enumerate(item.get("sentence_info", [])):
        text = sent.get("text") or sent.get("sentence") or ""
        text = clean_text(text)
        if i < 3:
            logger.info(f"  si[{i}]: keys={list(sent.keys())} start={sent.get('start')} end={sent.get('end')} text_len={len(text)}")
        if not text:
            continue
        start = sent.get("start") or 0
        end = sent.get("end") or 0
        spk = sent.get("spk", "")
        if spk is not None and spk != "":
            spk = SPEAKER_LABEL_TEMPLATE.format(int(spk) + 1)
        else:
            spk = ""
        segments.append({
            "speaker": spk,
            "text": text,
            "start": float(start) / MS_PER_S,
            "end": float(end) / MS_PER_S,
        })

    if not segments:
        raw_text = item.get("text", "")
        if isinstance(raw_text, str):
            raw_text = clean_text(raw_text)
        timestamps = item.get("timestamp", [])
        logger.info(f"_parse_result fallback: raw_text_type={type(item.get('text')).__name__} ts_len={len(timestamps) if isinstance(timestamps, list) else 'N/A'}")
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
                        "start": float(ts[0] or 0) / MS_PER_S,
                        "end": float(ts[1] or 0) / MS_PER_S,
                    })
    logger.info(f"_parse_result: produced {len(segments)} segments, range {segments[0]['start']:.1f}-{segments[-1]['end']:.1f}s" if segments else "_parse_result: 0 segments")
    return segments
