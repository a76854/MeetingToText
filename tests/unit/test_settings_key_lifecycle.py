"""Regression tests for llm_api_key lifecycle (bugs B1 + M5).

- B1: POST /settings with an empty llm_api_key must mean "leave unchanged",
  never wipe the stored key. Explicit clears go through DELETE only.
- M5: DELETE /settings/{key} must reset the runtime settings object, not just
  the DB row, so GET /settings and /api/health agree with actual behavior.
"""

import pytest

pytestmark = pytest.mark.unit

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.services.store as store_mod
from backend.app.config import Settings, settings
from backend.app.routers.settings import router as settings_router
from backend.app.services.store import get_store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(store_mod, "_store", None)
    app = FastAPI()
    app.include_router(settings_router)
    return TestClient(app)


def _seed(monkeypatch, key: str, value: str):
    get_store().set_setting(key, value)
    monkeypatch.setattr(settings, key, value)


def test_post_empty_llm_api_key_keeps_stored_key(client, monkeypatch):
    _seed(monkeypatch, "llm_api_key", "sk-old")

    resp = client.post("/api/settings", json={"llm_api_key": ""})

    assert resp.status_code == 200
    assert get_store().get_setting("llm_api_key") == "sk-old"
    assert settings.llm_api_key == "sk-old"


def test_post_whitespace_llm_api_key_also_skipped(client, monkeypatch):
    _seed(monkeypatch, "llm_api_key", "sk-old")

    resp = client.post("/api/settings", json={"llm_api_key": "   "})

    assert resp.status_code == 200
    assert get_store().get_setting("llm_api_key") == "sk-old"
    assert settings.llm_api_key == "sk-old"


def test_post_new_llm_api_key_updates(client, monkeypatch):
    _seed(monkeypatch, "llm_api_key", "sk-old")

    resp = client.post("/api/settings", json={"llm_api_key": "sk-new"})

    assert resp.status_code == 200
    assert get_store().get_setting("llm_api_key") == "sk-new"
    assert settings.llm_api_key == "sk-new"


def test_delete_llm_api_key_clears_db_and_runtime(client, monkeypatch):
    _seed(monkeypatch, "llm_api_key", "sk-old")

    resp = client.delete("/api/settings/llm_api_key")

    assert resp.status_code == 200
    assert get_store().get_setting("llm_api_key", "") == ""
    assert settings.llm_api_key == ""
    assert bool(settings.llm_api_key) is False
    info = client.get("/api/settings").json()
    assert info["llm_api_key_set"] is False


def test_delete_other_key_resets_runtime_to_default(client, monkeypatch):
    _seed(monkeypatch, "llm_model", "my-custom-model")

    resp = client.delete("/api/settings/llm_model")

    assert resp.status_code == 200
    assert get_store().get_setting("llm_model", "") == ""
    assert settings.llm_model == Settings().llm_model


def test_delete_unknown_key_rejected(client):
    resp = client.delete("/api/settings/not_a_real_key")

    assert resp.status_code == 400
