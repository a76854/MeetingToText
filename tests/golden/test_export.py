"""Golden tests locking the TXT / SRT / MD export output formats.

These tests snapshot the CURRENT byte-for-byte output of the real exporters in
``backend/app/routers/export.py`` (imported directly — logic is NOT duplicated
here). They exist to catch silent format changes during later de-duplication
refactors of the text-building logic (e.g. pipeline.py:213-217 and
transcribe.py:106-111 build ``full_text`` with a ``"\\n\\n"`` separator, while
``_export_txt`` joins segments with a single ``"\\n"``).

If one of these tests fails after a refactor, the export format changed for
end users — that must be an explicit, reviewed decision (update the golden
strings in the same commit), never an accident.

Hermetic: no ASR model load, no DB, no network. The import chain of
``backend.app.routers.export`` only defines functions at module level.
"""

from backend.app.models.schemas import TaskInfo, TaskResult, TaskStatus, TranscriptSegment
from backend.app.services.exporters import (
    _export_md,
    _export_srt,
    _export_txt,
    _format_timestamp_srt,
)

# ---------------------------------------------------------------------------
# Fixed fixture A: 3 segments — two with speaker tags, one without (pins the
# "no speaker" branch of every exporter). full_text mirrors production
# construction (pipeline.py:213-217 / transcribe.py:106-111): same labeled
# lines but joined with "\n\n".
# ---------------------------------------------------------------------------
SEGMENT_DICTS = [
    {"start": 0.5, "end": 3.25, "speaker": "张三", "text": "大家好，我们开始开会。"},
    {"start": 61.0, "end": 65.5, "speaker": "李四", "text": "好的，我先汇报一下进度。"},
    {"start": 120.25, "end": 125.75, "speaker": "", "text": "这段没有说话人标签。"},
]


def _make_task_a() -> TaskInfo:
    segments = [TranscriptSegment(**d) for d in SEGMENT_DICTS]
    # Mirrors pipeline.py:213-217 exactly ("\n\n" separator) so tests can pin
    # the divergence between stored full_text and the TXT export.
    full_text = "\n\n".join(
        f"[{s['speaker']}] {s['text']}" if s["speaker"] else s["text"]
        for s in SEGMENT_DICTS
    )
    return TaskInfo(
        id="golden01",
        status=TaskStatus.done,
        filename="周会录音.mp3",
        result=TaskResult(segments=segments, full_text=full_text, duration=125.4),
        minutes="1. 讨论了项目进度\n2. 下周继续",
    )


# ---------------------------------------------------------------------------
# Golden strings — captured from the CURRENT behavior of the real exporters.
# Written as explicit per-line literals so every separator is visible.
# ---------------------------------------------------------------------------

GOLDEN_TXT = (
    "[张三] 大家好，我们开始开会。\n"
    "[李四] 好的，我先汇报一下进度。\n"
    "这段没有说话人标签。"
)

GOLDEN_SRT = (
    "1\n"
    "00:00:00,500 --> 00:00:03,250\n"
    "[张三] 大家好，我们开始开会。\n"
    "\n"
    "2\n"
    "00:01:01,000 --> 00:01:05,500\n"
    "[李四] 好的，我先汇报一下进度。\n"
    "\n"
    "3\n"
    "00:02:00,250 --> 00:02:05,750\n"
    "这段没有说话人标签。\n"
)

GOLDEN_MD = (
    "# 会议转录 — 周会录音.mp3\n"
    "\n"
    "> 时长: 2m5s  |  任务ID: `golden01`\n"
    "\n"
    "## 1. [0:00–0:03] 张三\n"
    "\n"
    "大家好，我们开始开会。\n"
    "\n"
    "## 2. [1:01–1:05] 李四\n"
    "\n"
    "好的，我先汇报一下进度。\n"
    "\n"
    "## 3. [2:00–2:05] 未知\n"
    "\n"
    "这段没有说话人标签。\n"
    "\n"
    "---\n"
    "\n"
    "# 会议纪要\n"
    "\n"
    "1. 讨论了项目进度\n"
    "2. 下周继续"
)


def test_txt_golden():
    """TXT export: single '\n' between segments (NOT '\n\n' like full_text)."""
    task = _make_task_a()
    out = _export_txt(task)
    assert out == GOLDEN_TXT, f"TXT format drifted:\n--- got ---\n{out!r}\n--- golden ---\n{GOLDEN_TXT!r}"
    # Pin the separator explicitly: TXT uses ONE newline; stored full_text uses TWO.
    assert "\n\n" not in out
    assert out.count("\n") == 2  # 3 segments -> exactly 2 separators
    assert not out.endswith("\n")
    assert task.result.full_text.count("\n\n") == 2  # contrast: full_text IS "\n\n"-joined


def test_srt_golden():
    """SRT export: numbered blocks with 'HH:MM:SS,mmm --> HH:MM:SS,mmm' lines,
    blank line after each block (trailing '\n' at EOF), comma decimal separator."""
    task = _make_task_a()
    out = _export_srt(task)
    assert out == GOLDEN_SRT, f"SRT format drifted:\n--- got ---\n{out!r}\n--- golden ---\n{GOLDEN_SRT!r}"
    assert out.endswith("\n")  # each block ends with a blank line, incl. the last
    assert out.count("\n\n") == 2  # exactly one blank line BETWEEN blocks
    lines = out.splitlines()
    assert lines[0] == "1" and lines[4] == "2" and lines[8] == "3"  # 1-based indices
    assert lines[1] == "00:00:00,500 --> 00:00:03,250"  # comma ms separator, ' --> ' arrow
    assert lines[9] == "00:02:00,250 --> 00:02:05,750"


def test_md_golden():
    """MD export: H1 title, blockquote metadata (backticked task id), numbered
    H2 headings with en-dash time ranges, '未知' fallback speaker, '---' hr +
    '# 会议纪要' minutes section. (No **bold** markers exist in current MD.)"""
    task = _make_task_a()
    out = _export_md(task)
    assert out == GOLDEN_MD, f"MD format drifted:\n--- got ---\n{out!r}\n--- golden ---\n{GOLDEN_MD!r}"
    assert out.startswith("# 会议转录 — 周会录音.mp3")
    assert "> 时长: 2m5s  |  任务ID: `golden01`" in out  # sub-hour duration branch
    assert "## 1. [0:00–0:03] 张三" in out  # en-dash U+2013 between timestamps
    assert "## 3. [2:00–2:05] 未知" in out  # empty speaker -> 未知 fallback
    assert "---\n\n# 会议纪要" in out


# ---------------------------------------------------------------------------
# Fixture B: hour-scale branches (duration >= 3600 and segment start >= 3600).
# ---------------------------------------------------------------------------

GOLDEN_MD_HOUR = (
    "# 会议转录 — long.mp3\n"
    "\n"
    "> 时长: 1h1m1s  |  任务ID: `golden02`\n"
    "\n"
    "## 1. [1:01:01–1:01:03] 王五\n"
    "\n"
    "散会前确认一下结论。\n"
)


def test_md_hour_branch_golden():
    """Pins the h-branch formatting of both the duration line and segment
    timestamps ('H:MM:SS', single-digit hour, no zero padding on hour)."""
    task = TaskInfo(
        id="golden02",
        status=TaskStatus.done,
        filename="long.mp3",
        result=TaskResult(
            segments=[TranscriptSegment(start=3661.5, end=3663.25, speaker="王五", text="散会前确认一下结论。")],
            full_text="[王五] 散会前确认一下结论。",
            duration=3661.0,
        ),
        minutes=None,
    )
    out = _export_md(task)
    assert out == GOLDEN_MD_HOUR, f"MD hour-branch drifted:\n--- got ---\n{out!r}"


def test_srt_timestamp_formatting_edges():
    """Timestamp helper pins: comma before ms, 3-digit ms rounding, negative clamp."""
    assert _format_timestamp_srt(0.5) == "00:00:00,500"
    assert _format_timestamp_srt(3661.25) == "01:01:01,250"
    assert _format_timestamp_srt(-1.2) == "00:00:00,000"  # negative clamps to zero
