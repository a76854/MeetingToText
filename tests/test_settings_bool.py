"""Regression tests for boolean setting storage/parsing/defaults (C1+C2+C3).

- C1: _BOOL_FIELDS covers all four bool keys (matches server.py _BOOL_KEYS).
- C3: POSTed bools are stored in app_settings as lowercase "true"/"false",
  never Python's capitalized "True"/"False".
- C2: GET /settings derives bool defaults from the runtime settings object,
  so MTT_* env boot values are visible, and parses every stored value with
  .lower() == "true".
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.routers.settings as settings_router_mod
import backend.app.services.store as store_mod
from backend.app.config import settings
from backend.app.routers.settings import router as settings_router
from backend.app.services.store import get_store

BOOL_KEYS = ["asr_needs_punc", "streaming_asr_enabled", "browser_noise_suppression", "asr_merge_vad"]


class _StubStreamingASR:
    @classmethod
    def get_instance(cls, model_name):
        return cls()

    def load(self):
        pass

    @classmethod
    def unload_all(cls):
        pass


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(store_mod, "_store", None)
    # Keep the POST side effects hermetic: no real ASR unload / streaming load.
    monkeypatch.setattr(settings_router_mod, "unload_all_asr", lambda: None)
    monkeypatch.setattr(settings_router_mod, "StreamingASR", _StubStreamingASR)
    app = FastAPI()
    app.include_router(settings_router)
    return TestClient(app)


@pytest.mark.parametrize("key", BOOL_KEYS)
@pytest.mark.parametrize("value", [True, False])
def test_post_bool_stores_lowercase_round_trip(client, key, value):
    resp = client.post("/api/settings", json={key: value})

    assert resp.status_code == 200
    stored = get_store().get_setting(key)
    assert stored == ("true" if value else "false")
    runtime = getattr(settings, key)
    assert runtime is value


def test_get_bool_defaults_reflect_runtime_settings(client, monkeypatch):
    # Simulate an MTT_STREAMING_ASR_ENABLED=true boot: no DB row exists,
    # only the runtime settings object carries the env-provided value.
    monkeypatch.setattr(settings, "streaming_asr_enabled", True)

    info = client.get("/api/settings").json()

    assert info["streaming_asr_enabled"] is True


def test_get_parses_legacy_capitalized_bool_rows(client):
    # Rows written before C3 hold capitalized "True"/"False"; GET must still
    # parse them correctly via the uniform .lower() == "true" rule.
    store = get_store()
    store.set_setting("browser_noise_suppression", "True")
    store.set_setting("asr_merge_vad", "False")

    info = client.get("/api/settings").json()

    assert info["browser_noise_suppression"] is True
    assert info["asr_merge_vad"] is False


def test_post_asr_model_type_derives_needs_punc(client):
    # C8: asr_needs_punc has exactly one rule — derived from asr_model_type
    # by the POST setdefault. A payload WITHOUT asr_needs_punc must still
    # persist the correct flag ("true" for paraformer, "false" otherwise).
    store = get_store()

    resp = client.post("/api/settings", json={"asr_model_type": "sensevoice"})
    assert resp.status_code == 200
    assert store.get_setting("asr_needs_punc") == "false"
    assert settings.asr_needs_punc is False

    resp = client.post("/api/settings", json={"asr_model_type": "paraformer"})
    assert resp.status_code == 200
    assert store.get_setting("asr_needs_punc") == "true"
    assert settings.asr_needs_punc is True
