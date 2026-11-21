"""Gemini story understanding, dialogue and camera work.

Talks to the Generative Language REST API directly with httpx - no SDK
dependency, and the same request shape works against any compatible endpoint.

Includes resilient retry logic:
  * Exponential backoff with jitter for transient 5xx / 429 / network errors
  * Automatic model fallback chain (pro -> flash -> flash-lite)
  * Circuit breaker that pauses requests after repeated failures
  * Auto-discovery: fetches available models from API on first 404
"""

from __future__ import annotations

import random
import time
from typing import Any

import httpx

from ..config import get_settings
from ..logging_config import get_logger
from .base import BaseLLM, ProviderError

log = get_logger("providers.gemini")

# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #


class _CircuitBreaker:
    """Simple in-memory circuit breaker for the Gemini provider."""

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._last_failure: float | None = None
        self._state = "closed"  # closed | open | half_open

    @property
    def state(self) -> str:
        if self._state == "open":
            if self._last_failure is not None:
                elapsed = time.monotonic() - self._last_failure
                if elapsed >= self.cooldown_seconds:
                    self._state = "half_open"
                    self._failures = 0
                    log.info("circuit breaker entering half-open state")
        return self._state

    def record_success(self) -> None:
        self._failures = 0
        if self._state in ("open", "half_open"):
            self._state = "closed"
            log.info("circuit breaker closed after success")

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure = time.monotonic()
        if self._failures >= self.failure_threshold:
            self._state = "open"
            log.warning(
                "circuit breaker OPEN after %d consecutive failures "
                "(cooldown=%.0fs)",
                self._failures,
                self.cooldown_seconds,
            )

    def check(self) -> None:
        if self.state == "open":
            remaining = self.cooldown_seconds - (time.monotonic() - (self._last_failure or 0))
            raise ProviderError(
                f"Gemini circuit breaker is OPEN. "
                f"Retry after {max(0, int(remaining))}s."
            )


_circuit = _CircuitBreaker(failure_threshold=5, cooldown_seconds=60.0)

# --------------------------------------------------------------------------- #
# Retry helpers
# --------------------------------------------------------------------------- #


def _is_retryable(exc: Exception) -> bool:
    """Return True if the exception looks transient and worth retrying.

    404 (model not found) is NOT retryable — but we use auto-discovery
    to find working models instead of hard-coding them.
    """
    msg = str(exc).lower()
    # 503 = Service Unavailable, 429 = Too Many Requests, 502 = Bad Gateway,
    # 504 = Gateway Timeout, connection errors, read timeouts
    retryable_codes = ("503", "429", "502", "504")
    retryable_phrases = (
        "unavailable",
        "too many requests",
        "rate limit",
        "high demand",
        "timeout",
        "connect",
        "read timeout",
        "connection",
        "temporary",
    )
    if any(code in msg for code in retryable_codes):
        return True
    return any(phrase in msg for phrase in retryable_phrases)


def _is_model_not_found(exc: Exception) -> bool:
    """Return True if the error is a 404 model not found."""
    msg = str(exc).lower()
    return "404" in msg or "not found" in msg or "no longer available" in msg


def _backoff_delay(attempt: int, base: float = 2.0, cap: float = 30.0) -> float:
    """Exponential backoff with full jitter."""
    exp = base * (2 ** attempt)
    return min(exp, cap) * random.random()


# --------------------------------------------------------------------------- #
# Auto-discovery: fetch available models from API
# --------------------------------------------------------------------------- #


def _discover_models(api_key: str, base_url: str) -> list[str]:
    """Fetch available Gemini models from the API and return text-capable ones."""
    try:
        url = f"{base_url}/v1beta/models"
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                url,
                params={"key": api_key, "pageSize": 100},
            )
        if response.status_code != 200:
            log.warning("model discovery failed: %s", response.status_code)
            return []

        data = response.json()
        models = []
        for m in data.get("models", []):
            name = m.get("name", "").replace("models/", "")
            # Only text-generation models (not embeddings, TTS, etc.)
            supported = m.get("supportedGenerationMethods", [])
            if "generateContent" in supported and "embedContent" not in supported:
                # Skip image-only, TTS, robotics, etc.
                skip_keywords = ("image", "tts", "transcribe", "live", "embedding",
                                 "robotics", "computer-use", "native-audio")
                if not any(kw in name.lower() for kw in skip_keywords):
                    models.append(name)

        # Sort: pro first, then flash, then lite
        def _rank(m: str) -> int:
            if "-pro" in m.lower():
                return 0
            if "-flash" in m.lower() and "-lite" not in m.lower():
                return 1
            if "-lite" in m.lower():
                return 2
            return 3

        models.sort(key=_rank)
        log.info("discovered %d text models: %s", len(models), ", ".join(models[:6]))
        return models

    except Exception as exc:
        log.warning("model discovery error: %s", exc)
        return []


# --------------------------------------------------------------------------- #
# Gemini LLM
# --------------------------------------------------------------------------- #


class GeminiLLM(BaseLLM):
    name = "gemini"

    # Sensible defaults — auto-discovery replaces these on first 404
    FALLBACK_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
    ]

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = (api_key if api_key is not None else settings.gemini_api_key).strip()
        self.model = model or settings.gemini_model
        self.base_url = (base_url or settings.gemini_base_url).rstrip("/")
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY is not set")
        self._discovered: list[str] | None = None

    # -- internal request -----------------------------------------------------

    def _call_generate(
        self,
        model: str,
        system: str,
        user: str,
        timeout: float = 120.0,
    ) -> str:
        """Make one HTTP request to the Gemini API."""
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.75,
                "topP": 0.95,
                "maxOutputTokens": 4096,
                "responseMimeType": "application/json",
            },
        }
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    url,
                    params={"key": self.api_key},
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"gemini request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"gemini returned {response.status_code}: {response.text[:400]}"
            )

        try:
            payload = response.json()
            candidates = payload.get("candidates") or []
            if not candidates:
                feedback = payload.get("promptFeedback", {})
                raise ProviderError(f"gemini returned no candidates: {feedback}")
            parts = candidates[0].get("content", {}).get("parts") or []
            text = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"unexpected gemini response shape: {exc}") from exc

        if not text.strip():
            finish = candidates[0].get("finishReason", "unknown")
            raise ProviderError(f"gemini returned empty text (finishReason={finish})")
        return text

    # -- resilient generate with retry + fallback + auto-discovery -----------

    def _generate(self, system: str, user: str) -> str:
        """Call Gemini with retries, model fallback, and circuit breaker."""
        _circuit.check()

        # Build the model chain: primary first, then fallbacks
        models = [self.model]
        for m in self.FALLBACK_MODELS:
            if m != self.model and m not in models:
                models.append(m)

        max_retries = 3
        last_error: Exception | None = None
        discovered_once = False

        for model in models:
            for attempt in range(max_retries):
                try:
                    log.debug(
                        "gemini call model=%s attempt=%d/%d",
                        model,
                        attempt + 1,
                        max_retries,
                    )
                    result = self._call_generate(model, system, user)
                    _circuit.record_success()
                    if model != self.model:
                        log.info(
                            "gemini fallback succeeded: switched from %s to %s",
                            self.model,
                            model,
                        )
                    return result

                except ProviderError as exc:
                    last_error = exc

                    # On first 404, auto-discover available models and rebuild chain
                    if _is_model_not_found(exc) and not discovered_once:
                        discovered_once = True
                        log.warning(
                            "model %s not found — auto-discovering available models...",
                            model,
                        )
                        discovered = _discover_models(self.api_key, self.base_url)
                        if discovered:
                            # Rebuild model chain from discovered models
                            new_models = []
                            if self.model in discovered:
                                new_models.append(self.model)
                            for d in discovered:
                                if d not in new_models:
                                    new_models.append(d)
                            models = new_models
                            log.info(
                                "rebuilt model chain: %s",
                                ", ".join(models[:4]),
                            )
                            # Restart loop with new chain
                            return self._generate_with_models(system, user, models)

                    if not _is_retryable(exc):
                        # Hard error — don't retry, try next fallback
                        log.warning(
                            "gemini model=%s non-retryable error: %s",
                            model,
                            str(exc)[:200],
                        )
                        break

                    # Transient error — backoff and retry
                    delay = _backoff_delay(attempt)
                    log.warning(
                        "gemini model=%s attempt %d/%d failed: %s — "
                        "retrying in %.1fs",
                        model,
                        attempt + 1,
                        max_retries,
                        str(exc)[:200],
                        delay,
                    )
                    time.sleep(delay)

            # Exhausted retries for this model, move to next fallback
            log.warning(
                "gemini model=%s exhausted all %d retries, trying next fallback",
                model,
                max_retries,
            )

        # All models failed
        _circuit.record_failure()
        raise ProviderError(
            f"gemini failed after trying {len(models)} model(s) "
            f"with {max_retries} retries each: {last_error}"
        ) from last_error

    def _generate_with_models(
        self, system: str, user: str, models: list[str]
    ) -> str:
        """Generate using a specific model list (used after auto-discovery)."""
        max_retries = 3
        last_error: Exception | None = None

        for model in models:
            for attempt in range(max_retries):
                try:
                    result = self._call_generate(model, system, user)
                    _circuit.record_success()
                    return result
                except ProviderError as exc:
                    last_error = exc
                    if not _is_retryable(exc):
                        break
                    delay = _backoff_delay(attempt)
                    time.sleep(delay)

        _circuit.record_failure()
        raise ProviderError(
            f"gemini failed after auto-discovery and trying {len(models)} model(s): {last_error}"
        ) from last_error


def build_gemini_llm() -> GeminiLLM:
    return GeminiLLM()
