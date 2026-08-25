"""Hermetic unit tests for backend/app/services/llm.py (todo 3).

llm.py previously had zero coverage. These tests PIN current behavior:

- LLMClient.generate assembles the system/user message list and passes
  temperature/max_tokens (and the model override) straight through to the
  OpenAI-compatible SDK boundary.
- SDK exceptions propagate unwrapped out of generate(); the error wrapping
  lives one layer up in routers/generate.py, so this file must NOT add any.
- get_llm caches one module-level instance; update_llm_config swaps that
  instance so the next get_llm returns the new config.

Hermeticity: llm.OpenAI is monkeypatched with a recording fake, so no real
client is ever constructed and zero network requests happen. The module-global
_llm_instance is saved/restored per test so no fake (or settings-built real
client) leaks into other suites.
"""

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

pytestmark = pytest.mark.unit

from backend.app.config import settings
from backend.app.services import llm


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    """Shape of openai's ChatCompletion as consumed by llm.py:38."""

    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _RecordingCompletions:
    """Stands in for client.chat.completions; records create() kwargs."""

    def __init__(self):
        self.calls = []
        self.result = None
        self.error = None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat(_RecordingCompletions())


@pytest.fixture(autouse=True)
def _isolate_llm_singleton(monkeypatch):
    """Save/restore the module-global _llm_instance.

    monkeypatch.setattr snapshots the ORIGINAL value and restores it at
    teardown, so each test starts from a clean None and never leaks a fake
    or settings-built client into other suites (llm.py:41 is a global).
    """
    monkeypatch.setattr(llm, "_llm_instance", None)


@pytest.fixture()
def fake_sdk(monkeypatch):
    """Monkeypatch llm.OpenAI with a factory returning a recording fake."""
    fake_client = _FakeClient()
    factory_calls: list[dict] = []

    def fake_openai_factory(  # noqa: E501
        base_url=None, api_key=None, timeout=None, max_retries=None, **_ignored
    ):
        factory_calls.append(
            {
                "base_url": base_url,
                "api_key": api_key,
                "timeout": timeout,
                "max_retries": max_retries,
            }
        )
        return fake_client

    monkeypatch.setattr(llm, "OpenAI", fake_openai_factory)
    return fake_client, factory_calls


def test_generate_success_assembles_messages_and_passes_params(fake_sdk):
    fake_client, factory_calls = fake_sdk
    fake_client.chat.completions.result = _FakeResponse("会议纪要内容")

    client = llm.LLMClient(
        base_url="https://fake.example/v1",
        api_key="secret-key",
        model="deepseek-chat",
    )
    out = client.generate(
        system_prompt="你是一名会议纪要助手",
        user_message="这是转写文本",
        temperature=0.7,
        max_tokens=128,
    )

    assert out == "会议纪要内容"
    # SDK boundary: the lazy client property built OpenAI() with the config.
    assert factory_calls == [
        {
            "base_url": "https://fake.example/v1",
            "api_key": "secret-key",
            "timeout": 60.0,
            "max_retries": 2,
        }
    ]
    # Exactly one create() call carrying assembled messages and params.
    (create_kwargs,) = fake_client.chat.completions.calls
    assert create_kwargs["model"] == "deepseek-chat"  # falls back to self.model
    assert create_kwargs["messages"] == [
        {"role": "system", "content": "你是一名会议纪要助手"},
        {"role": "user", "content": "这是转写文本"},
    ]
    assert create_kwargs["temperature"] == 0.7
    assert create_kwargs["max_tokens"] == 128


def test_generate_propagates_sdk_exception_unwrapped(fake_sdk):
    fake_client, _ = fake_sdk
    fake_client.chat.completions.error = RuntimeError("api unreachable")

    client = llm.LLMClient(model="deepseek-chat")

    # Current behavior: the SDK exception escapes generate() untouched;
    # routers/generate.py is the layer that converts it into a 500.
    with pytest.raises(RuntimeError, match="api unreachable"):
        client.generate(system_prompt="sys", user_message="usr")


def test_generate_empty_content_falls_back_to_empty_string(fake_sdk):
    fake_client, _ = fake_sdk
    fake_client.chat.completions.result = _FakeResponse(None)

    client = llm.LLMClient(model="m")

    # llm.py:38 `... or ""` — a None content must not become a crash.
    assert client.generate(system_prompt="s", user_message="u") == ""


def test_generate_model_override_beats_client_default(fake_sdk):
    fake_client, _ = fake_sdk
    fake_client.chat.completions.result = _FakeResponse("ok")

    client = llm.LLMClient(model="deepseek-chat")
    client.generate(system_prompt="s", user_message="u", model="override-model")

    (create_kwargs,) = fake_client.chat.completions.calls
    assert create_kwargs["model"] == "override-model"


def test_update_llm_config_replaces_singleton(fake_sdk):
    llm.update_llm_config(
        base_url="https://new.example",
        api_key="new-key",
        model="new-model",
    )

    instance = llm.get_llm()

    assert isinstance(instance, llm.LLMClient)
    assert instance.base_url == "https://new.example"
    assert instance.api_key == "new-key"
    assert instance.model == "new-model"


def test_get_llm_caches_single_instance(fake_sdk):
    first = llm.get_llm()
    second = llm.get_llm()

    # Same object, no rebuild (llm.py:45-56 double-checked cache).
    assert first is second
    # First call built it from runtime settings...
    assert first.base_url == settings.llm_base_url
    assert first.api_key == settings.llm_api_key
    assert first.model == settings.llm_model
    # ...and never touched the SDK boundary (lazy client still unbuilt).
    assert first._client is None


def test_client_construction_sets_timeout_and_retries(fake_sdk):
    fake_client, factory_calls = fake_sdk
    client = llm.LLMClient(base_url="https://x.example", api_key="k", model="m")
    _ = client.client  # trigger lazy OpenAI construction
    assert factory_calls[0]["timeout"] == 60.0
    assert factory_calls[0]["max_retries"] == 2


# ------------------------------------------------------------------ map_llm_error


def _make_auth_error() -> AuthenticationError:
    req = httpx.Request("GET", "https://api.example/v1/chat/completions")
    resp = httpx.Response(401, request=req)
    return AuthenticationError(message="invalid key xyz", response=resp, body=None)


def _make_rate_limit_error() -> RateLimitError:
    req = httpx.Request("GET", "https://api.example/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    return RateLimitError(message="rate limited detail xyz", response=resp, body=None)


def test_map_llm_error_timeout():
    req = httpx.Request("GET", "https://api.example/v1/chat/completions")
    exc = APITimeoutError(request=req)
    msg = llm.map_llm_error(exc)
    assert msg == "连接 LLM 服务失败，请检查网络或稍后重试"
    assert "xyz" not in msg and str(exc) not in msg


def test_map_llm_error_connection():
    req = httpx.Request("GET", "https://api.example/v1/chat/completions")
    exc = APIConnectionError(request=req)
    msg = llm.map_llm_error(exc)
    assert msg == "连接 LLM 服务失败，请检查网络或稍后重试"


def test_map_llm_error_authentication():
    exc = _make_auth_error()
    msg = llm.map_llm_error(exc)
    assert msg == "LLM API Key 无效或未授权，请在设置中检查"
    # Must not leak raw exception text (which contains "invalid key xyz")
    assert "invalid key" not in msg
    assert "xyz" not in msg


def test_map_llm_error_rate_limit():
    exc = _make_rate_limit_error()
    msg = llm.map_llm_error(exc)
    assert msg == "LLM 服务请求过于频繁，请稍后重试"
    assert "rate limited" not in msg


def test_map_llm_error_fallback_generic():
    exc = RuntimeError("boom secret sk-12345")
    msg = llm.map_llm_error(exc)
    assert msg == "LLM 调用失败，请检查服务可用性或联系管理员"
    assert "boom" not in msg
    assert "sk-12345" not in msg


def test_map_llm_error_fallback_malformed_custom():
    # Adversarial: weird custom exception shape must still fall back generically
    class WeirdError(Exception):
        def __str__(self):
            return "weird payload with key=sk-weird and url=https://evil"

    exc: Exception = WeirdError()
    msg = llm.map_llm_error(exc)
    assert msg == "LLM 调用失败，请检查服务可用性或联系管理员"
    assert "weird" not in msg
    assert "sk-weird" not in msg
