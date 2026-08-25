"""Router-level tests for upload.py and audio.py (todo 6 of teaching-refactor).

Covers, against a MINIMAL FastAPI app mounting ONLY these two routers:

  upload.py   POST /api/upload      legal extension -> task created + file kept
                                    illegal extension -> 400 (extension filter)
                                    oversized body -> 413 (size limit branch)
                                    empty body -> 400 (empty-file branch)
  audio.py    GET  /api/audio/{id}  existing file -> 200 + mime from _AUDIO_MIME
                                    unknown task -> 404 "Task not found"
                                    task whose file vanished -> 404 "音频文件不存在"

Why minimal app instead of backend.app.server: the full server pulls CORS,
static SPA fallback and a model-preloading lifespan — side effects that have
nothing to do with these two routers and would slow the suite down.

Hermeticity: every test redirects settings.data_dir into tmp_path (upload_dir/
temp_dir/db_path are all properties derived from data_dir), and resets the
store singleton so get_store() rebuilds a TaskStore against the tmp SQLite DB.
No writes ever reach the real data/ directory; tests assert artifacts land
under tmp_path only. Response shapes are pinned verbatim so the refactor in
later todos (task 8 import move, task 21 get_task_or_404, task 22 DELETE
shapes) must preserve them byte-for-byte.
"""

import os

import pytest

pytestmark = pytest.mark.integration
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.routers.audio as audio_module
import backend.app.routers.upload as upload_module
import backend.app.services.store as store_module
from backend.app.config import settings
from backend.app.services.store import create_task, get_task

# upload.py:13 — extension filter table. Driven from the module constant so
# the test tracks the source of truth instead of re-inventing it.
ALLOWED = upload_module.ALLOWED_EXTENSIONS

# Verbatim error payloads the routes emit today (refactor must keep them).
ILLEGAL_EXT_PREFIX = "不支持的文件格式，支持: "
EMPTY_FILE_DETAIL = "空文件"
TASK_NOT_FOUND_DETAIL = "Task not found"
AUDIO_FILE_MISSING_DETAIL = "音频文件不存在"
MAGIC_MISMATCH_DETAIL = "文件内容与音频格式不符"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Minimal app + tmp data_dir + fresh store singleton, per test.

    - settings.data_dir -> tmp_path redirects upload_dir/temp_dir/db_path in
      one move (all are @property derivations, config.py:66-80).
    - config.py ran os.makedirs at import time against the REAL data_dir, so
      the redirect needs its own directories (upload.py opens filepath with
      "wb" directly).
    - store._store -> None forces get_store() to rebuild a TaskStore against
      the tmp db_path on first use (store.py:219-225 double-checked cache);
      monkeypatch restores the previous singleton value on teardown.
    """
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.temp_dir, exist_ok=True)
    monkeypatch.setattr(store_module, "_store", None)

    app = FastAPI()
    app.include_router(upload_module.router)
    app.include_router(audio_module.router)
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ upload


def test_upload_legal_wav_creates_task_and_persists_file(client, tmp_path):
    payload = b"RIFF" + b"\x00" * 64  # route only streams bytes; no decode here
    resp = client.post(
        "/api/upload", files={"file": ("meeting.wav", payload, "audio/wav")}
    )

    assert resp.status_code == 200
    body = resp.json()
    # UploadResponse (schemas.py:55) carries exactly these two keys.
    assert body == {"task_id": body["task_id"], "filename": "meeting.wav"}

    task = get_task(body["task_id"])
    assert task is not None
    assert task.filename == "meeting.wav"
    assert task.status.value == "pending"
    # File landed under the redirected upload_dir, not the real data/ tree.
    assert task.audio_path.startswith(str(tmp_path))
    assert os.path.exists(task.audio_path)
    with open(task.audio_path, "rb") as f:
        assert f.read() == payload


def test_upload_illegal_extension_returns_400(client):
    resp = client.post(
        "/api/upload",
        files={"file": ("notes.exe", b"malware", "application/octet-stream")},
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail.startswith(ILLEGAL_EXT_PREFIX)
    # set iteration order is not stable across hash seeds — pin the table
    # members instead of the exact join order.
    for ext in ALLOWED:
        assert ext in detail
    # Rejected before any file I/O: upload dir stays clean.
    assert os.listdir(settings.upload_dir) == []


def test_upload_oversized_body_returns_413(client, monkeypatch):
    # upload.py:32 reads settings.max_upload_bytes at request time — shrink it
    # instead of shipping 500MB over the test client.
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    resp = client.post(
        "/api/upload", files={"file": ("big.wav", b"x" * 100, "audio/wav")}
    )

    assert resp.status_code == 413
    # upload.py:50-53: 10 bytes // (1024*1024) == 0 -> "文件超过 0MB 限制".
    assert resp.json() == {"detail": "文件超过 0MB 限制"}
    # overflow branch (upload.py:45-49) removes the partial file.
    assert os.listdir(settings.upload_dir) == []


def test_upload_empty_file_returns_400(client):
    resp = client.post(
        "/api/upload", files={"file": ("empty.wav", b"", "audio/wav")}
    )

    assert resp.status_code == 400
    assert resp.json() == {"detail": EMPTY_FILE_DETAIL}
    # empty-file branch (upload.py:55-60) removes the touched file too.
    assert os.listdir(settings.upload_dir) == []


# ------------------------------------------------------------------- audio


@pytest.mark.parametrize(
    "ext,media_type",
    [
        (".wav", "audio/wav"),
        (".mp3", "audio/mpeg"),
        (".flac", "audio/flac"),
        (".webm", "audio/webm"),
    ],
)
def test_get_audio_serves_stored_file_with_mime(client, tmp_path, ext, media_type):
    payload = b"\x01\x02\x03\x04" * 8
    path = tmp_path / f"sample{ext}"
    path.write_bytes(payload)
    task = create_task(filename=f"sample{ext}", audio_path=str(path))

    resp = client.get(f"/api/audio/{task.id}")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == media_type
    assert resp.content == payload


def test_get_audio_unknown_task_returns_404(client):
    resp = client.get("/api/audio/does-not-exist")

    assert resp.status_code == 404
    assert resp.json() == {"detail": TASK_NOT_FOUND_DETAIL}


def test_get_audio_task_with_missing_file_returns_404(client, tmp_path):
    task = create_task(
        filename="gone.wav", audio_path=str(tmp_path / "gone.wav")
    )

    resp = client.get(f"/api/audio/{task.id}")

    assert resp.status_code == 404
    assert resp.json() == {"detail": AUDIO_FILE_MISSING_DETAIL}


# ---------------------------------------------------------------- magic + precheck (task 11)


def test_upload_wav_magic_mismatch_returns_400_and_no_file_leak(client):
    before = os.listdir(settings.upload_dir)
    resp = client.post(
        "/api/upload",
        files={"file": ("fake.wav", b"MZ" + b"\x90\x00" * 32, "audio/wav")},
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": MAGIC_MISMATCH_DETAIL}
    assert os.listdir(settings.upload_dir) == before
    assert os.listdir(settings.upload_dir) == []


def test_upload_wav_valid_minimal_header_passes(client, tmp_path):
    payload = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE" + b"fmt " + b"\x10\x00\x00\x00" + b"\x00" * 20
    resp = client.post(
        "/api/upload", files={"file": ("real.wav", payload, "audio/wav")}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "real.wav"
    task = get_task(body["task_id"])
    assert task is not None
    assert task.audio_path.startswith(str(tmp_path))
    assert os.path.exists(task.audio_path)
    with open(task.audio_path, "rb") as f:
        assert f.read() == payload


def test_upload_content_length_precheck_returns_413_and_no_disk_write(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    payload = b"RIFF" + b"\x00" * 64
    resp = client.post(
        "/api/upload", files={"file": ("small.wav", payload, "audio/wav")}
    )
    assert resp.status_code == 413
    assert resp.json() == {"detail": "文件超过 0MB 限制"}
    assert os.listdir(settings.upload_dir) == []


def test_upload_mp3_magic_mismatch_returns_400(client):
    resp = client.post(
        "/api/upload",
        files={"file": ("fake.mp3", b"MZ" + b"\x00" * 32, "audio/mpeg")},
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": MAGIC_MISMATCH_DETAIL}
    assert os.listdir(settings.upload_dir) == []
