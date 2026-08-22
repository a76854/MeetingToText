"""Regression tests for SPA fallback path traversal (server.py spa_fallback).

Before the fix, GET /../../backend/app/config.py served Python source because
os.path.join(frontend_dist, full_path) escaped the dist root and isfile() passed.
"""
import sys
import os

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.server import app  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TRAVERSAL_PATHS = [
    "/%2e%2e/%2e%2e/backend/app/config.py",
    "/../../backend/app/config.py",
    "/..%2f..%2fbackend/app/config.py",
    "/assets/../../backend/app/config.py",
]

PYTHON_SOURCE_MARKERS = [b"import ", b"def ", b"class ", b"settings"]


def _is_python_source(body: bytes) -> bool:
    return any(marker in body for marker in PYTHON_SOURCE_MARKERS)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("path", TRAVERSAL_PATHS)
def test_traversal_does_not_serve_python_source(client, path):
    resp = client.get(path)
    assert resp.status_code == 404 or resp.status_code == 200
    if resp.status_code == 200:
        assert not _is_python_source(resp.content), (
            f"{path} leaked file content outside frontend/dist"
        )
        assert b"<!DOCTYPE html>" in resp.content or b"<html" in resp.content.lower()


def test_normal_route_still_serves_index_html(client):
    for path in ("/", "/tasks", "/settings"):
        resp = client.get(path)
        assert resp.status_code == 200
        content = resp.content
        assert b"<!DOCTYPE html>" in content or b"<html" in content.lower(), (
            f"{path} did not serve index.html"
        )


def test_legitimate_dist_file_still_served(client):
    from backend.app.server import frontend_dist

    index = os.path.join(frontend_dist, "index.html")
    if not os.path.isfile(index):
        pytest.skip("frontend/dist/index.html not built")
    resp = client.get("/index.html")
    assert resp.status_code == 200
    assert resp.content == open(index, "rb").read()
