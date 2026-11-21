"""Gemini image generation provider.

Uses the Gemini REST API directly (same httpx approach as llm_gemini.py).
No SDK dependency — works with any imagen/flash-image model.

Improvements over original:
  * Direct REST API call — no google-genai SDK needed
  * Model fallback chain: tries multiple image models on failure
  * Detailed emotion-driven prompt construction
  * Proper error logging so mock fallback is visible in logs
  * strict_providers respected to surface real errors
"""

from __future__ import annotations

import base64
import random
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings
from ..logging_config import get_logger
from .base import ImageProvider, ImageRequest, ImageResult, ProviderError
from .image_mock import MockImageProvider

log = get_logger("providers.image.gemini")

# ---------------------------------------------------------------------------
# Image model fallback chain — verified available on new API keys (Oct 2026)
# ---------------------------------------------------------------------------
IMAGE_MODEL_CHAIN = [
    "gemini-3.1-flash-image",
    "gemini-3-pro-image",
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
]


def _is_retryable_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    retryable = ("503", "429", "502", "504", "unavailable",
                 "too many requests", "rate limit", "timeout", "temporary")
    return any(k in msg for k in retryable)


def _is_model_not_found(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "404" in msg or "not found" in msg or "no longer available" in msg


def _backoff(attempt: int) -> float:
    return min(2.0 * (2 ** attempt), 30.0) * random.random()


class GeminiImageProvider(ImageProvider):
    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = (api_key if api_key is not None else settings.gemini_api_key).strip()
        self.base_url = settings.gemini_base_url.rstrip("/")
        # Primary model from config; fallback chain covers the rest
        self.model = (model or settings.gemini_image_model or "gemini-3.1-flash-image").strip()
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY is not set")

    @property
    def supports_reference_images(self) -> bool:
        return True

    # ------------------------------------------------------------------ prompt

    def _build_prompt(self, request: ImageRequest) -> str:
        """Build a rich, emotion-forward prompt for the image model."""
        names = ", ".join(request.character_names) if request.character_names else "the character"
        scene = request.setting or request.action or "a dramatic scene"

        # Emotion → vivid facial description
        emotion_map = {
            "joy": "beaming smile, sparkling eyes, raised cheeks, warm expression",
            "happiness": "bright warm smile, wide joyful eyes, lifted cheeks",
            "sadness": "downcast eyes, trembling lower lip, tears forming, slumped posture",
            "anger": "narrowed fierce eyes, furrowed brows, clenched jaw, flared nostrils",
            "fear": "wide terrified eyes, raised eyebrows, open mouth, pale face",
            "surprise": "eyes wide open in shock, eyebrows raised high, mouth agape",
            "disgust": "wrinkled nose, curled upper lip, squinting eyes",
            "contempt": "one corner of mouth raised in a sneer, cold narrowed eyes",
            "determination": "set jaw, focused intense eyes, tight-lipped expression",
            "grief": "eyes red and wet with tears, trembling chin, deeply furrowed brows",
            "wonder": "wide bright eyes, slight open-mouthed awe, raised eyebrows",
            "calm": "relaxed soft eyes, gentle closed-lip expression, serene look",
            "neutral": "relaxed natural expression, soft eyes, slight thoughtful look",
        }
        emotion = (request.emotion or "neutral").lower()
        face_detail = emotion_map.get(emotion, f"{emotion} expression clearly visible on face")

        negative = (
            request.negative_prompt
            or "blurry, low quality, bad anatomy, mutated hands, extra fingers, "
               "deformed face, blank expression, emotionless face, flat lifeless eyes, "
               "poorly drawn, watermark, text overlay, oversaturated"
        )

        return (
            f"High-quality {request.style} comic panel. "
            f"Scene: {scene}. "
            f"Characters: {names}. "
            f"Action: {request.action or 'present in scene'}. "
            f"FACIAL EXPRESSION (CRITICAL — must be clearly visible): {face_detail}. "
            f"Camera: {request.shot} shot. "
            f"Lighting: {request.time_of_day} atmosphere. "
            f"Detailed prompt: {request.prompt}. "
            "Art requirements: sharp detailed linework, expressive faces, "
            "professional comic book quality, dynamic composition, "
            "characters with distinct recognisable features. "
            f"Negative: {negative}."
        )

    # ------------------------------------------------------------------ API call

    def _call_api(self, model: str, prompt: str, timeout: float = 120.0) -> bytes:
        """Call Gemini image generation REST endpoint. Returns raw image bytes."""
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        body: dict[str, Any] = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]}
            ],
            "generationConfig": {
                "responseModalities": ["IMAGE", "TEXT"],
            },
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    url,
                    params={"key": self.api_key},
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"gemini image request failed: {exc}") from exc

        if resp.status_code >= 400:
            raise ProviderError(
                f"gemini image returned {resp.status_code}: {resp.text[:400]}"
            )

        return self._extract_image_bytes(resp.json())

    def _extract_image_bytes(self, payload: dict) -> bytes:
        """Pull raw image bytes out of the generateContent response."""
        for candidate in payload.get("candidates") or []:
            parts = (candidate.get("content") or {}).get("parts") or []
            for part in parts:
                # REST API returns base64 under inlineData
                inline = part.get("inlineData") or part.get("inline_data")
                if inline:
                    data = inline.get("data") or ""
                    if data:
                        try:
                            return base64.b64decode(data)
                        except Exception:
                            return bytes(data) if isinstance(data, (bytes, bytearray)) else b""
        return b""

    # ------------------------------------------------------------------ generate

    def generate(self, request: ImageRequest) -> ImageResult:
        settings = get_settings()
        prompt = self._build_prompt(request)

        # Build model chain: primary first, then fallbacks
        chain = [self.model]
        for m in IMAGE_MODEL_CHAIN:
            if m not in chain:
                chain.append(m)

        last_error: Exception | None = None

        for model in chain:
            for attempt in range(3):
                try:
                    log.debug(
                        "gemini image model=%s attempt=%d panel=%s",
                        model, attempt + 1, request.panel_id,
                    )
                    image_bytes = self._call_api(model, prompt)

                    if not image_bytes:
                        raise ProviderError(
                            f"gemini model={model} returned empty image for panel {request.panel_id}"
                        )

                    # Success — write to disk
                    output = Path(request.output_path)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(image_bytes)
                    log.info(
                        "gemini image panel=%s model=%s size=%d bytes",
                        request.panel_id, model, len(image_bytes),
                    )
                    if model != self.model:
                        log.info(
                            "gemini image fallback: used %s instead of %s",
                            model, self.model,
                        )
                    return ImageResult(
                        path=str(output),
                        provider=self.name,
                        seed=request.seed,
                        meta={"model": model, "prompt": prompt[:300]},
                    )

                except ProviderError as exc:
                    last_error = exc
                    if _is_model_not_found(exc):
                        log.warning("gemini image model=%s not found, trying next", model)
                        break  # skip to next model immediately
                    if not _is_retryable_error(exc):
                        log.warning(
                            "gemini image model=%s non-retryable: %s",
                            model, str(exc)[:200],
                        )
                        break
                    delay = _backoff(attempt)
                    log.warning(
                        "gemini image model=%s attempt=%d failed: %s — retry in %.1fs",
                        model, attempt + 1, str(exc)[:200], delay,
                    )
                    time.sleep(delay)

        # All models exhausted — raise instead of silently mocking
        error_msg = f"Gemini image generation failed for panel {request.panel_id}: {last_error}"
        log.error(error_msg)

        if settings.strict_providers:
            raise ProviderError(error_msg) from last_error

        # Non-strict: fall back to mock but make it loud
        log.error(
            "FALLING BACK TO MOCK for panel %s — Gemini failed with: %s. "
            "Check GEMINI_IMAGE_MODEL and GEMINI_API_KEY in .env",
            request.panel_id, last_error,
        )
        return MockImageProvider().generate(request)


def build_gemini_image_provider() -> GeminiImageProvider:
    return GeminiImageProvider()
