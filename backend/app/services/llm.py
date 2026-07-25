import logging
import time

from openai import OpenAI, APITimeoutError, APIError
from httpx import Timeout as HttpxTimeout

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 2


def estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def truncate_text(text: str, max_input_tokens: int) -> tuple[str, bool]:
    max_chars = max_input_tokens * _CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text, False
    half = max_chars // 2
    truncated = text[:half] + "\n\n......(中间内容已截断)......\n\n" + text[-half:]
    logger.warning(
        "Transcript truncated from %d chars (~%d tokens) to %d chars (~%d tokens)",
        len(text), estimate_tokens(text), len(truncated), estimate_tokens(truncated),
    )
    return truncated, True


class LLMClient:
    def __init__(self, base_url: str = "", api_key: str = "", model: str = ""):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self._client = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                max_retries=0,
                timeout=HttpxTimeout(connect=10.0, read=300.0, write=60.0),
            )
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model: str = "",
        max_input_tokens: int = 128000,
    ) -> str:
        resolved_model = model or self.model

        if max_input_tokens > 0:
            user_message, truncated = truncate_text(user_message, max_input_tokens)
        else:
            truncated = False

        estimated_input = estimate_tokens(system_prompt) + estimate_tokens(user_message)
        logger.info(
            "LLM request model=%s estimated_input=%d max_output=%d truncated=%s",
            resolved_model, estimated_input, max_tokens, truncated,
        )

        t0 = time.time()
        try:
            response = self.client.chat.completions.create(
                model=resolved_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except APITimeoutError:
            elapsed = time.time() - t0
            logger.error("LLM request timed out after %.1fs model=%s", elapsed, resolved_model)
            raise
        except APIError as e:
            elapsed = time.time() - t0
            logger.error(
                "LLM request failed after %.1fs model=%s status=%s body=%s",
                elapsed, resolved_model, e.status_code, e.body,
            )
            raise

        elapsed = time.time() - t0
        usage = getattr(response, "usage", None)
        if usage:
            logger.info(
                "LLM response elapsed=%.1fs prompt=%s completion=%s total=%s model=%s",
                elapsed, usage.prompt_tokens, usage.completion_tokens,
                usage.total_tokens, resolved_model,
            )
        else:
            logger.info(
                "LLM response elapsed=%.1fs (no usage info) model=%s",
                elapsed, resolved_model,
            )

        return response.choices[0].message.content or ""


_llm_instance: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm_instance
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
    _llm_instance = LLMClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
    )
