"""Llama via Ollama (or any OpenAI-compatible local server through OLLAMA_BASE_URL).

Uses Ollama's native ``/api/chat`` with ``format: "json"``. Kept behind the same
LLMProvider interface as Gemini, so swapping is one environment variable.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings
from ..logging_config import get_logger
from .base import BaseLLM, ProviderError

log = get_logger("providers.ollama")


class OllamaLLM(BaseLLM):
    name = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        if not self.base_url:
            raise ProviderError("OLLAMA_BASE_URL is not set")

    def health(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                return client.get(f"{self.base_url}/api/tags").status_code == 200
        except httpx.HTTPError:
            return False

    def _generate(self, system: str, user: str) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.75, "num_ctx": 8192},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            with httpx.Client(timeout=300.0) as client:
                response = client.post(f"{self.base_url}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"could not reach Ollama at {self.base_url}: {exc}. "
                f"Is it running (`ollama serve`) and has `{self.model}` been pulled?"
            ) from exc

        if response.status_code >= 400:
            raise ProviderError(f"ollama returned {response.status_code}: {response.text[:400]}")

        try:
            payload = response.json()
            text = payload.get("message", {}).get("content", "")
        except ValueError as exc:
            raise ProviderError(f"unexpected ollama response: {exc}") from exc

        if not text.strip():
            raise ProviderError("ollama returned an empty response")
        return text


def build_ollama_llm() -> OllamaLLM:
    return OllamaLLM()
