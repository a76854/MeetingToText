"""Readiness probe tests for routers/health.py (todo 13).

Covers live DB + disk checks against a minimal FastAPI app mounting ONLY
health.router, with tmp_path-backed data_dir. Mirrors sibling integration
fixtures (settings.data_dir redirect + store singleton reset) for hermeticity.

Cases:
- healthy → 200 ok / db ok / disk ok + disk_free_mb numeric
- DB unreachable (monkeypatch sqlite3.connect to raise) → 503 db error
- DB path is a directory → 503 db error
- Disk low via huge MTT_HEALTH_MIN_DISK_MB threshold → 503 disk low
- Config echo: llm_configured + asr_model reflect settings
- Both components failing → 503 unhealthy
"""

import os
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.routers.health as health_module
import backend.app.services.store as store_module
from backend.app.config import settings

pytestmark = pytest.mark.integration


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.temp_dir, exist_ok=True)
    monkeypatch.setattr(store_module, "_store", None)
    # Ensure env threshold is default for isolation; individual tests override.
    monkeypatch.delenv("MTT_HEALTH_MIN_DISK_MB", raising=False)
    app = FastAPI()
    app.include_router(health_module.router)
    with TestClient(app) as c:
        yield c


def test_health_healthy_returns_200_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["disk"] == "ok"
    assert isinstance(body["disk_free_mb"], int)
    assert body["disk_free_mb"] >= 0
    # Config echo present
    assert "llm_configured" in body
    assert "asr_model" in body
    assert isinstance(body["llm_configured"], bool)
    assert isinstance(body["asr_model"], str)


def test_health_db_unreachable_returns_503(client, monkeypatch):
    def _raise(*_a, **_kw):
        raise sqlite3.OperationalError("cannot open database")

    monkeypatch.setattr(health_module.sqlite3, "connect", _raise)

    resp = client.get("/api/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["db"] == "error"
    # disk still reported (even if ok), free mb present
    assert "disk_free_mb" in body
    assert "llm_configured" in body
    assert "asr_model" in body


def test_health_db_path_is_directory_returns_503(client, tmp_path):
    db_dir = settings.db_path
    if os.path.isfile(db_dir):
        os.remove(db_dir)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    if not os.path.isdir(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    resp = client.get("/api/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unhealthy"
    assert resp.json()["db"] == "error"


def test_health_disk_low_via_huge_threshold_returns_503(client, monkeypatch):
    monkeypatch.setenv("MTT_HEALTH_MIN_DISK_MB", "99999999")

    resp = client.get("/api/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["disk"] == "low"
    assert body["db"] == "ok"
    assert isinstance(body["disk_free_mb"], int)


def test_health_response_contains_config_echo(client, monkeypatch):
    # llm_configured reflects settings.llm_api_key truthiness
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-123")
    monkeypatch.setattr(settings, "asr_model_type", "paraformer")

    resp = client.get("/api/health")
    # healthy state still 200, echo must reflect patched values
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_configured"] is True
    assert body["asr_model"] == "paraformer"

    monkeypatch.setattr(settings, "llm_api_key", "")
    resp2 = client.get("/api/health")
    assert resp2.json()["llm_configured"] is False
    assert resp2.json()["asr_model"] == "paraformer"


def test_health_both_db_and_disk_fail_returns_503(client, monkeypatch):
    def _raise(*_a, **_kw):
        raise sqlite3.OperationalError("db down")

    monkeypatch.setattr(health_module.sqlite3, "connect", _raise)
    monkeypatch.setenv("MTT_HEALTH_MIN_DISK_MB", "99999999")

    resp = client.get("/api/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["db"] == "error"
    assert body["disk"] == "low"


def test_health_db_probe_uses_timeout_2(client, monkeypatch):
    captured: dict[str, object] = {}

    orig_connect = sqlite3.connect

    def _capture(path, timeout=2, **kw):
        captured["timeout"] = timeout
        captured["path"] = path
        return orig_connect(path, timeout=timeout, **kw)

    monkeypatch.setattr(health_module.sqlite3, "connect", _capture)

    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert captured.get("timeout") == 2
