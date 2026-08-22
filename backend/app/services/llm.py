from openai import OpenAI
import threading


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
