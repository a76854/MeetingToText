import os
import pytest

pytestmark = pytest.mark.integration

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.routers.upload as upload_module
import backend.app.services.store as store_module
from backend.app.config import settings
from backend.app.services.store import create_task


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.temp_dir, exist_ok=True)
    monkeypatch.setattr(store_module, "_store", None)
    app = FastAPI()
    app.include_router(upload_module.router)
    with TestClient(app) as c:
        yield c


def _create_task(tmp_path, filename="orig.wav"):
    path = tmp_path / filename
    path.write_bytes(b"RIFF\x00\x00\x00\x00")
    return create_task(filename=filename, audio_path=str(path))


def test_rename_success_and_visible_in_get_and_list(client, tmp_path):
    task = _create_task(tmp_path, "meeting.wav")
    resp = client.put(f"/api/task/{task.id}/name", json={"name": "周会-产品评审"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "name": "周会-产品评审"}

    resp = client.get(f"/api/task/{task.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "周会-产品评审"
    assert body["filename"] == "meeting.wav"

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    matched = [t for t in tasks if t["id"] == task.id]
    assert len(matched) == 1
    assert matched[0]["name"] == "周会-产品评审"
    assert matched[0]["filename"] == "meeting.wav"


def test_rename_trims_whitespace(client, tmp_path):
    task = _create_task(tmp_path, "a.wav")
    resp = client.put(f"/api/task/{task.id}/name", json={"name": "  hello  "})
    assert resp.status_code == 200
    assert resp.json()["name"] == "hello"
    resp = client.get(f"/api/task/{task.id}")
    assert resp.json()["name"] == "hello"


def test_rename_empty_clears(client, tmp_path):
    task = _create_task(tmp_path, "b.wav")
    client.put(f"/api/task/{task.id}/name", json={"name": "some"})
    resp = client.put(f"/api/task/{task.id}/name", json={"name": ""})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "name": ""}
    assert client.get(f"/api/task/{task.id}").json()["name"] == ""
    tasks = client.get("/api/tasks").json()["tasks"]
    matched = [t for t in tasks if t["id"] == task.id][0]
    assert matched["name"] == ""

    resp = client.put(f"/api/task/{task.id}/name", json={"name": "   "})
    assert resp.status_code == 200
    assert resp.json()["name"] == ""


def test_rename_404_for_missing_task(client):
    resp = client.put("/api/task/does-not-exist/name", json={"name": "x"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Task not found"}


def test_rename_overlong_returns_400(client, tmp_path):
    task = _create_task(tmp_path, "c.wav")
    long_name = "a" * 201
    resp = client.put(f"/api/task/{task.id}/name", json={"name": long_name})
    assert resp.status_code == 400
    assert "200" in resp.json()["detail"] or "超过" in resp.json()["detail"]

    exact = "a" * 200
    resp = client.put(f"/api/task/{task.id}/name", json={"name": exact})
    assert resp.status_code == 200
    assert resp.json()["name"] == exact


def test_rename_does_not_alter_filename_on_disk(client, tmp_path):
    task = _create_task(tmp_path, "orig.wav")
    original_path = task.audio_path
    client.put(f"/api/task/{task.id}/name", json={"name": "new display"})
    fetched = client.get(f"/api/task/{task.id}").json()
    assert fetched["filename"] == "orig.wav"
    assert fetched["audio_path"] == original_path
    assert os.path.exists(original_path)


def test_recorder_filename_format_regex(monkeypatch, tmp_path):
    import re
    import asyncio
    from backend.app.services.recorder import recorder_manager
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    os.makedirs(settings.temp_dir, exist_ok=True)
    task_id = "abc123"
    path = asyncio.run(recorder_manager.start_recording(task_id))
    try:
        basename = os.path.basename(path)
        assert re.match(r"^record_abc123_\d{12}\.wav$", basename), f"basename {basename!r} does not match expected pattern"
        assert re.match(r"^record_.+_\d{12}\.wav$", basename)
    finally:
        asyncio.run(recorder_manager.cancel_recording(task_id))
