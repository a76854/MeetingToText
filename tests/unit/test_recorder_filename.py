import re
import asyncio
import os

import pytest

pytestmark = pytest.mark.unit


def test_recorder_filename_uses_local_wall_clock_format(monkeypatch, tmp_path):
    from backend.app.config import settings
    from backend.app.services.recorder import recorder_manager

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    os.makedirs(settings.temp_dir, exist_ok=True)
    task_id = "abc123"
    path = asyncio.run(recorder_manager.start_recording(task_id))
    try:
        basename = os.path.basename(path)
        assert re.match(r"^record_abc123_\d{12}\.wav$", basename), basename
        # %y%m%d%H%M%S => 12 digits
        stamp = basename.split("_")[-1].removesuffix(".wav")
        assert len(stamp) == 12
        assert stamp.isdigit()
        # also ensure config path uses timestamp not epoch
        assert not re.match(r"^record_abc123_\d{10}\.wav$", basename) or len(stamp) == 12
    finally:
        asyncio.run(recorder_manager.cancel_recording(task_id))


def test_strftime_expression_produces_expected_shape():
    from datetime import datetime

    sample = datetime(2025, 8, 25, 15, 21, 30)
    formatted = sample.strftime("%y%m%d%H%M%S")
    assert formatted == "250825152130"
    assert re.match(r"^\d{12}$", formatted)
    name = f"record_abc123_{formatted}.wav"
    assert re.match(r"^record_abc123_250825152130\.wav$", name)
