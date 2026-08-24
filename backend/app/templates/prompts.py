"""Prompt assembly for LLM minutes generation.

This module turns a template's prompt data plus a transcript into the exact
``messages`` list handed to ``LLMClient.generate`` (services/llm.py:31-34).
It is pure string plumbing — no settings, no store, no LLM access — so the
wording contract lives in one place and can be unit-tested hermetically.

Teaching notes (the WHY behind the shape):

- **system vs user separation.** The system message carries the stable
  *persona and format contract* ("you are a meeting secretary, obey these
  rules, output in this shape"). The user message carries the *per-task
  payload*: the transcript to summarize and any per-request custom
  instructions. OpenAI-compatible APIs treat the system role as
  higher-priority steering instructions; keeping per-request input out of it
  means a hostile or oversized transcript cannot re-steer the persona.

- **output_format injection point.** The format hint (e.g. a Markdown
  skeleton) is appended to the SYSTEM message, because it constrains the
  assistant's output shape — the same message every request with that
  template shares. It is only appended when non-empty, so templates without
  a format section (presets.py) send the bare system prompt.

- **custom instructions inject into the USER message.** They are
  request-scoped additions ("额外要求：...") about THIS transcript, not the
  assistant's standing role. Appending them to the user message also keeps
  them adjacent to the text they modify, and their absence produces no
  empty "额外要求：" segment at all (no blank suffix is ever appended).

Template data (system prompts, format hints) lives in the sibling module
``backend.app.templates.presets``; this module only assembles what it is given.
"""

# Format suffixes extracted verbatim from the original inline assembly at
# backend/app/routers/generate.py:37-45 (todo 10 extraction — do not reword,
# these bytes are pinned by tests/test_prompts.py).
_OUTPUT_FORMAT_SUFFIX = "\n\n请按照以下格式输出：\n{output_format}"
_TRANSCRIPT_SCAFFOLD = (
    "请根据以下会议转录内容生成会议纪要：\n\n"
    "=== 会议转录开始 ===\n{transcript}\n=== 会议转录结束 ==="
)
_CUSTOM_INSTRUCTIONS_SUFFIX = "\n\n额外要求：{custom_instructions}"


def build_minutes_messages(
    template_prompt: str,
    transcript_text: str,
    custom_instructions: str | None,
    output_format_hint: str = "",
) -> list[dict]:
    """Assemble the chat messages for one minutes-generation request.

    Args:
        template_prompt: the template's ``system_prompt`` (presets.py).
        transcript_text: the task's ``result.full_text`` to summarize.
        custom_instructions: optional per-request appendix; ``None`` or an
            empty string produces no "额外要求" segment.
        output_format_hint: the template's ``output_format`` (presets.py);
            when non-empty it is appended to the system prompt as a
            "请按照以下格式输出" block.

    Returns:
        A two-element list in OpenAI chat shape::

            [
                {"role": "system", "content": <template_prompt + format hint>},
                {"role": "user", "content": <transcript scaffold + custom reqs>},
            ]

        The returned strings are byte-identical to the assembly formerly
        inlined in generate.py (see module docstring).
    """
    system_prompt = template_prompt
    if output_format_hint:
        system_prompt += _OUTPUT_FORMAT_SUFFIX.format(output_format=output_format_hint)

    user_message = _TRANSCRIPT_SCAFFOLD.format(transcript=transcript_text)

    if custom_instructions:
        user_message += _CUSTOM_INSTRUCTIONS_SUFFIX.format(
            custom_instructions=custom_instructions
        )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
