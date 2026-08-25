"""Unit tests for backend/app/templates/prompts.build_minutes_messages.

These are the prompt-string assertions deliberately deferred by todo 7
(see the PROMPT-ASSERTIONS-PORTED-BY-TODO-10 marker in
tests/test_routers_transcribe_generate.py:42-50). That file pins the router
seam (kwarg KEYS only); this file pins the actual BYTES of the assembled
messages, because the wording is the contract a teacher reads.

Everything here is a hermetic pure-function test: template data comes from
the real backend/app/templates/presets.TEMPLATES (the single source of
truth), the transcript and custom instructions are local literals, and no
LLM / store / network is touched. No conftest.py involvement — fixtures, if
any, live in this file only.
"""

import pytest

pytestmark = pytest.mark.unit

from backend.app.templates.presets import TEMPLATES, get_template
from backend.app.templates.prompts import build_minutes_messages

TRANSCRIPT = "张经理：今天的重点是预算。\n李工：好，我补充一下排期。"


def _template(template_id: str) -> dict:
    t = get_template(template_id)
    assert t is not None, f"preset missing: {template_id}"
    return t


# ------------------------------------------------------------ system role


def test_system_message_is_template_prompt_plus_format_hint():
    """System role carries the template persona PLUS the output-format block.

    Ports the deferred assertion for generate.py:37-40: the suffix is
    "\n\n请按照以下格式输出：\n" + output_format, appended only when non-empty.
    """
    t = _template("meeting_minutes")
    messages = build_minutes_messages(
        template_prompt=t["system_prompt"],
        transcript_text=TRANSCRIPT,
        custom_instructions=None,
        output_format_hint=t["output_format"],
    )
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == (
        t["system_prompt"] + "\n\n请按照以下格式输出：\n" + t["output_format"]
    )


def test_empty_output_format_hint_adds_no_suffix():
    """output_format_hint="" (or absent) -> bare system prompt, no "请按照以下格式输出"."""
    t = _template("meeting_minutes")
    for hint in ("", None):
        messages = build_minutes_messages(
            template_prompt=t["system_prompt"],
            transcript_text=TRANSCRIPT,
            custom_instructions=None,
            output_format_hint=hint,
        )
        assert messages[0]["content"] == t["system_prompt"]
        assert "请按照以下格式输出" not in messages[0]["content"]


# ------------------------------------------------------------- user role


def test_user_message_fences_transcript_exactly():
    """User role scaffolds the transcript inside the "=== 会议转录开始 ===" fence.

    Ports the deferred assertion for generate.py:42-43, byte for byte.
    """
    messages = build_minutes_messages(
        template_prompt="system",
        transcript_text=TRANSCRIPT,
        custom_instructions=None,
        output_format_hint="",
    )
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == (
        "请根据以下会议转录内容生成会议纪要：\n\n"
        f"=== 会议转录开始 ===\n{TRANSCRIPT}\n=== 会议转录结束 ==="
    )


def test_custom_instructions_appended_to_user_message():
    """custom_instructions present -> "\n\n额外要求：<text>" appendix on the USER role."""
    messages = build_minutes_messages(
        template_prompt="system",
        transcript_text=TRANSCRIPT,
        custom_instructions="不要输出表格",
        output_format_hint="",
    )
    assert messages[1]["content"].endswith("\n\n额外要求：不要输出表格")
    # The appendix is user-scoped: the system message stays untouched.
    assert messages[0]["content"] == "system"


def test_absent_custom_instructions_leave_no_empty_segment():
    """None / "" custom instructions -> no "额外要求" segment at all (no blank suffix)."""
    for missing in (None, ""):
        messages = build_minutes_messages(
            template_prompt="system",
            transcript_text=TRANSCRIPT,
            custom_instructions=missing,
            output_format_hint="",
        )
        assert "额外要求" not in messages[1]["content"]
        assert not messages[1]["content"].endswith("\n\n")


# ------------------------------------------------------- structure & parity


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_two_message_chat_shape_for_every_preset(template_id):
    """Every preset template yields exactly [system, user] with non-empty content."""
    t = _template(template_id)
    messages = build_minutes_messages(
        template_prompt=t["system_prompt"],
        transcript_text=TRANSCRIPT,
        custom_instructions="额外要求测试",
        output_format_hint=t.get("output_format", ""),
    )
    assert [m["role"] for m in messages] == ["system", "user"]
    assert set(messages[0]) == {"role", "content"} and set(messages[1]) == {"role", "content"}
    assert t["system_prompt"] in messages[0]["content"]
    assert TRANSCRIPT in messages[1]["content"]
    if t.get("output_format"):
        assert "请按照以下格式输出" in messages[0]["content"]
    assert messages[1]["content"].endswith("额外要求测试")
