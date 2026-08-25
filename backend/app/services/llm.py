import threading

from openai import APIConnectionError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError


class LLMClient:
    def __init__(self, base_url: str = "", api_key: str = "", model: str = ""):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=60.0,
                max_retries=2,
            )
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model: str = "",
    ) -> str:
        response = self.client.chat.completions.create(
            model=model or self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""


_llm_instance: LLMClient | None = None
_llm_lock = threading.Lock()


def get_llm() -> LLMClient:
    global _llm_instance
    if _llm_instance is None:
        with _llm_lock:
            if _llm_instance is None:
                from backend.app.config import settings
                _llm_instance = LLMClient(
                    base_url=settings.llm_base_url,
                    api_key=settings.llm_api_key,
                    model=settings.llm_model,
                )
    return _llm_instance


def update_llm_config(base_url: str, api_key: str, model: str):
    global _llm_instance
    with _llm_lock:
        _llm_instance = LLMClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
        )


def map_llm_error(exc: Exception) -> str:
    """Map SDK exceptions to sanitized Chinese messages.

    WHY generic: the 500 detail is user-facing and must never embed raw
    exception text (which may leak API keys, URLs, or internal stack
    traces). The raw exception is preserved server-side via
    logger.exception in the router; clients only see these fixed strings.
    Logs stay English elsewhere per CONTRIBUTING.
    """
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        return "连接 LLM 服务失败，请检查网络或稍后重试"
    if isinstance(exc, AuthenticationError):
        return "LLM API Key 无效或未授权，请在设置中检查"
    if isinstance(exc, RateLimitError):
        return "LLM 服务请求过于频繁，请稍后重试"
    return "LLM 调用失败，请检查服务可用性或联系管理员"
