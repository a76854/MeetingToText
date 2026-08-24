"""Monkey-patch for FunASR's CAM++ speaker-diariazation helper.

Why this vendor patch exists
----------------------------
FunASR's ``funasr.models.campplus.utils.distribute_spk`` (aliased in
``funasr.auto.auto_model``) assigns speaker ids to ASR sentences by matching
each sentence's time range against the diarization timeline. The upstream
implementation assumes every entry of ``sd_time_list`` is a non-empty 3-tuple
``(start_s, end_s, spk)`` with non-None timestamps.

What breaks without it
----------------------
- Empty / malformed diarization entries (which CAM++ produces on short or
  noisy audio) crash the generator *after* ASR succeeds — the whole
  transcription fails with a TypeError/IndexError instead of falling back to
  unlabeled sentences.
- Sentences whose ``start``/``end`` are None (VAD gaps) crash the overlap
  arithmetic; upstream does not guard them.
- With an empty timeline the upstream version drops speaker info entirely or
  raises, rather than defaulting every sentence to speaker 0.

What this patch does
--------------------
Replaces ``distribute_spk`` with a defensive re-implementation that:
- skips empty/None entries and normalizes start/end to milliseconds
  (``MS_PER_S`` from ``asr_parse``),
- defaults missing speaker ids and None-timestamped sentences to speaker 0,
- assigns each sentence the speaker with the largest temporal overlap,
- falls back to ``spk=0`` for every sentence when the timeline is unusable.

It patches both ``funasr.models.campplus.utils.distribute_spk`` and the
``funasr.auto.auto_model.distribute_spk`` alias, guarded by a ``_mt_patched``
flag so re-application is a no-op.

Risk when upgrading funasr
--------------------------
This patch is pinned to the current FunASR call signature
``distribute_spk(sentence_list, sd_time_list)`` and its internal data shapes
(start/end in seconds, 3-element tuples). A funasr upgrade may change the
signature, the time unit, or the module layout — the patch then silently
stops matching the vendor code and speaker assignment can break again, or
worse, mislabel speakers. After any funasr version bump: verify
``apply_funasr_distribute_spk_patch`` still applies (watch the
``_mt_patched`` guard) and re-run multi-speaker transcription tests.
"""

from backend.app.services.asr_parse import MS_PER_S


def apply_funasr_distribute_spk_patch() -> None:
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
            cleaned.append((float(st) * MS_PER_S, float(ed) * MS_PER_S, spk))

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
