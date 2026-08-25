"""Integration tests for GET /api/templates (template preview fields).

Verifies that the templates endpoint returns system_prompt and output_format
for each default template, enabling the frontend preview panel.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers.generate import router

pytestmark = pytest.mark.integration

@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


def test_templates_returns_all_default_templates(client):
    """GET /api/templates returns at least 3 templates."""
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert "templates" in body
    assert len(body["templates"]) >= 3


def test_templates_contain_preview_fields(client):
    """Each template must carry system_prompt and output_format."""
    resp = client.get("/api/templates")
    body = resp.json()
    for tpl in body["templates"]:
        assert "system_prompt" in tpl, f"Missing system_prompt on {tpl['id']}"
        assert "output_format" in tpl, f"Missing output_format on {tpl['id']}"
        assert isinstance(tpl["system_prompt"], str)
        assert isinstance(tpl["output_format"], str)


def test_templates_preview_fields_are_non_empty(client):
    """All default templates have non-empty preview content."""
    resp = client.get("/api/templates")
    body = resp.json()
    assert len(body["templates"]) >= 3
    for tpl in body["templates"]:
        assert len(tpl["system_prompt"]) > 0, f"Empty system_prompt on {tpl['id']}"
        assert len(tpl["output_format"]) > 0, f"Empty output_format on {tpl['id']}"


def test_templates_original_fields_preserved(client):
    """id, name, description still present alongside new preview fields."""
    resp = client.get("/api/templates")
    body = resp.json()
    for tpl in body["templates"]:
        assert "id" in tpl and isinstance(tpl["id"], str)
        assert "name" in tpl and isinstance(tpl["name"], str)
        assert "description" in tpl and isinstance(tpl["description"], str)
