"""Hermetic unit tests for ``backend/app/services/asr_parse.py``.

Locks the pure parsing layer of the ASR pipeline: the two FunASR output
shapes (``sentence_info`` list vs ``raw_text`` + ``timestamp`` fallback),
the millisecond-to-second conversion, speaker label rendering, and the
text cleaning regexes.

Hermetic by construction: ``asr_parse`` imports only ``logging`` and
``re``, and this file imports nothing from funasr / modelscope / torch.
"""

import pytest

pytestmark = pytest.mark.unit

from backend.app.services.asr_parse import (
    MS_PER_S,
    SPEAKER_LABEL_TEMPLATE,
    clean_text,
    parse_result,
)


class TestSentenceInfoShape:
    def test_speaker_labels_and_ms_to_s_conversion(self):
        result = [{
            "text": "unused when sentence_info present",
            "sentence_info": [
                {"text": "你好", "start": 1000, "end": 2500, "spk": 0},
                {"text": "好的", "start": 3000, "end": 4000, "spk": 1},
                {"text": "明白", "start": 4000, "end": 5500, "spk": 2},
            ],
        }]
        segments = parse_result(result)
        assert segments == [
            {"speaker": "说话人1", "text": "你好", "start": 1.0, "end": 2.5},
            {"speaker": "说话人2", "text": "好的", "start": 3.0, "end": 4.0},
            {"speaker": "说话人3", "text": "明白", "start": 4.0, "end": 5.5},
        ]

    def test_ms_to_s_is_exact_float_division(self):
        result = [{"sentence_info": [{"text": "精确", "start": 1234, "end": 5678, "spk": 0}]}]
        seg = parse_result(result)[0]
        assert seg["start"] == 1234 / MS_PER_S
        assert seg["end"] == 5678 / MS_PER_S

    def test_label_uses_shared_template(self):
        result = [{"sentence_info": [{"text": "甲", "start": 0, "end": 1000, "spk": 4}]}]
        assert parse_result(result)[0]["speaker"] == SPEAKER_LABEL_TEMPLATE.format(5)

    def test_missing_spk_yields_empty_speaker(self):
        result = [{"sentence_info": [{"text": "无标", "start": 0, "end": 1000}]}]
        seg = parse_result(result)[0]
        assert seg["speaker"] == ""

    def test_sentence_key_fallback_and_whitespace_skip(self):
        result = [{"sentence_info": [
            {"sentence": "用sentence键", "start": 0, "end": 1000, "spk": 0},
            {"text": "   ", "start": 1000, "end": 2000, "spk": 0},
        ]}]
        segments = parse_result(result)
        assert [s["text"] for s in segments] == ["用sentence键"]

    def test_missing_start_end_default_to_zero(self):
        result = [{"sentence_info": [{"text": "无时间", "spk": 0}]}]
        seg = parse_result(result)[0]
        assert seg["start"] == 0.0
        assert seg["end"] == 0.0


class TestFallbackShape:
    def test_single_raw_text_with_timestamps(self):
        result = [{"text": "整体文本", "timestamp": [[0, 1000], [1000, 2000]]}]
        # raw_text is a single str, so only the first timestamp gets a text.
        segments = parse_result(result)
        assert segments == [
            {"speaker": "", "text": "整体文本", "start": 0.0, "end": 1.0},
        ]

    def test_list_raw_text_with_timestamps(self):
        result = [{"text": ["第一句", "第二句"], "timestamp": [[0, 500], [500, 1000]]}]
        segments = parse_result(result)
        assert segments == [
            {"speaker": "", "text": "第一句", "start": 0.0, "end": 0.5},
            {"speaker": "", "text": "第二句", "start": 0.5, "end": 1.0},
        ]

    def test_fallback_used_only_when_sentence_info_empty(self):
        result = [{
            "text": "不该出现",
            "sentence_info": [],
            "timestamp": [[0, 1000]],
        }]
        assert parse_result(result) == [
            {"speaker": "", "text": "不该出现", "start": 0.0, "end": 1.0},
        ]

    def test_raw_text_still_cleaned_in_fallback(self):
        result = [{"text": "。，句首标点", "timestamp": [[0, 1000]]}]
        assert parse_result(result)[0]["text"] == "句首标点"


class TestEmptyAndGarbageInputs:
    def test_non_list_inputs(self):
        assert parse_result(None) == []
        assert parse_result("not a list") == []
        assert parse_result({}) == []

    def test_empty_list(self):
        assert parse_result([]) == []

    def test_empty_dict_item(self):
        assert parse_result([{}]) == []

    def test_none_text_and_none_timestamp(self):
        assert parse_result([{"text": None, "timestamp": None}]) == []

    def test_empty_string_text(self):
        assert parse_result([{"text": "", "sentence_info": []}]) == []

    def test_non_list_timestamp_ignored(self):
        assert parse_result([{"text": "abc", "timestamp": "nope"}]) == []

    def test_malformed_timestamp_entries_skipped(self):
        result = [{"text": ["a", "b"], "timestamp": [[0, 1000], "nope", [0]]}]
        assert parse_result(result) == [
            {"speaker": "", "text": "a", "start": 0.0, "end": 1.0},
        ]


class TestCleanText:
    def test_tag_stripping(self):
        # regex: r'<\|[^|>]+\|>'
        assert clean_text("<|zh|>你好") == "你好"
        assert clean_text("<|en|><|zh|>hello") == "hello"
        assert clean_text("开头<|nospeech|>结尾") == "开头结尾"

    def test_leading_punctuation_stripped(self):
        # regex: r'^[。，、；：！？,.!?:;]+'
        assert clean_text("。你好") == "你好"
        assert clean_text("，、；：！？世界") == "世界"
        assert clean_text(",.!?:;hello") == "hello"
        assert clean_text("。，、；：！？,.!?:;全删") == "全删"

    def test_trailing_punctuation_preserved(self):
        assert clean_text("你好。") == "你好。"
        assert clean_text("hello!") == "hello!"

    def test_whitespace_stripped(self):
        assert clean_text("  你好  ") == "你好"

    def test_combined_tag_and_punctuation(self):
        assert clean_text("<|zh|>。，你好") == "你好"
        assert clean_text("<|zh|>") == ""
