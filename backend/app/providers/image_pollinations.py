"""Pollinations.ai image generation provider.

Uses the Pollinations image API which wraps Flux/SD models. No API key is
required. Failed image requests are reported rather than replaced with mock art.

API: https://image.pollinations.ai/prompt/{url-encoded-prompt}?width=&height=&seed=&model=
Returns a PNG/JPEG directly — no polling, no auth.
"""

from __future__ import annotations

import io
import random
import threading
import time
import urllib.parse
from pathlib import Path

import httpx
from PIL import Image

from ..config import get_settings
from ..logging_config import get_logger
from .base import ImageProvider, ImageRequest, ImageResult, ProviderError

log = get_logger("providers.image.pollinations")

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
REQUEST_INTERVAL_SECONDS = 45.0
_rate_limit_lock = threading.Lock()
_next_request_at = 0.0
_rate_limit_until = 0.0


class PollinationsRateLimitError(ProviderError):
    """Pollinations rejected an image request due to its per-IP rate limit."""


def _wait_for_request_slot() -> None:
    global _next_request_at
    with _rate_limit_lock:
        now = time.monotonic()
        request_at = max(now, _next_request_at, _rate_limit_until)
        wait = request_at - now
        _next_request_at = request_at + REQUEST_INTERVAL_SECONDS

    if wait > 0:
        log.info("Pollinations per-IP rate limit: waiting %.1fs for the next image", wait)
        time.sleep(wait)


def _defer_after_rate_limit() -> None:
    global _next_request_at, _rate_limit_until
    with _rate_limit_lock:
        _rate_limit_until = max(
            _rate_limit_until,
            time.monotonic() + REQUEST_INTERVAL_SECONDS,
        )
        _next_request_at = max(_next_request_at, _rate_limit_until)

# Emotion → vivid facial description (drives expressive faces)
EMOTION_FACES = {
    "joy": "beaming smile, sparkling eyes, raised cheeks, warm radiant expression",
    "happiness": "bright warm smile, wide joyful eyes, lifted cheeks",
    "sadness": "downcast teary eyes, trembling lower lip, sorrowful expression",
    "anger": "narrowed fierce eyes, furrowed brows, clenched jaw, intense fury",
    "fear": "wide terrified eyes, raised eyebrows, open mouth, pale frightened face",
    "surprise": "eyes wide open in shock, eyebrows raised high, mouth agape",
    "disgust": "wrinkled nose, curled upper lip, squinting eyes",
    "contempt": "smirking sneer, cold narrowed eyes, raised chin",
    "determination": "set jaw, focused intense eyes, resolute expression",
    "grief": "red wet eyes full of tears, trembling chin, deep sorrow",
    "wonder": "wide bright awestruck eyes, open-mouthed amazement",
    "calm": "relaxed soft eyes, gentle serene expression",
    "neutral": "natural thoughtful expression, soft attentive eyes",
}

# Style → art style keywords for the model
STYLE_KEYWORDS = {
    "manga": "manga style, anime art, clean linework, screentone shading, expressive eyes",
    "comic": "western comic book style, bold ink lines, cel shading, dynamic",
    "noir": "film noir comic, high contrast black and white, dramatic shadows",
    "watercolor": "watercolor illustration, soft washes, painterly, delicate",
    "cartoon": "cartoon style, vibrant colors, clean shapes, playful",
    "realistic": "semi-realistic illustration, detailed rendering, cinematic",
}


class PollinationsImageProvider(ImageProvider):
    name = "pollinations"

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        # "flux" is the best free model; "turbo" is faster/lower quality
        self.model = model or "flux"
        self.image_size = settings.image_size or 768
        self.max_retries = 2

    @property
    def supports_reference_images(self) -> bool:
        # Pollinations URL API doesn't take reference images directly,
        # but we restate character appearance in the prompt for consistency.
        return False

    def _build_prompt(self, request: ImageRequest) -> str:
        names = ", ".join(request.character_names) if request.character_names else "the character"
        scene = request.setting or request.action or "a dramatic scene"

        emotion = (request.emotion or "neutral").lower()
        face = EMOTION_FACES.get(emotion, f"{emotion} expression clearly on face")

        style_kw = STYLE_KEYWORDS.get(
            (request.style or "manga").lower(),
            f"{request.style} comic art style",
        )

        parts = [
            style_kw,
            f"comic panel of {names}",
            f"{request.action or 'in scene'}",
            f"facial expression: {face}",
            f"setting: {scene}",
            f"{request.shot} shot composition",
            f"{request.time_of_day} lighting",
            request.prompt or "",
            "high quality, detailed, expressive faces, professional comic illustration",
        ]
        return ", ".join(p for p in parts if p.strip())

    def _fetch_image(self, prompt: str, seed: int, timeout: float = 90.0) -> bytes:
        # Append watermark-blocking keywords to prompt
        clean_prompt = prompt + ", no watermark, no text overlay, no logo, no signature"
        encoded = urllib.parse.quote(clean_prompt[:1800])
        url = f"{POLLINATIONS_BASE}/{encoded}"
        params = {
            "width": self.image_size,
            "height": self.image_size,
            "seed": seed,
            "model": self.model,
            "nologo": "true",    # Pollinations param to disable their watermark
            "nofeed": "true",    # Don't show in public feed
            "enhance": "true",
        }
        _wait_for_request_slot()
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"pollinations request failed: {exc}") from exc

        if resp.status_code >= 400:
            if resp.status_code == 402:
                _defer_after_rate_limit()
                raise PollinationsRateLimitError(
                    "Pollinations returned 402 (per-IP free-tier limit). "
                    f"Waiting {REQUEST_INTERVAL_SECONDS:.0f}s before retrying."
                )
            raise ProviderError(
                f"pollinations returned {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.content
        if not data or len(data) < 1000:  # sanity: real images are > 1KB
            raise ProviderError(
                f"pollinations returned suspiciously small response ({len(data)} bytes)"
            )
        # Basic content-type check
        ctype = resp.headers.get("content-type", "")
        if "image" not in ctype:
            raise ProviderError(f"pollinations returned non-image content-type: {ctype}")
        return data

    # ------------------------------------------------------------------ image cleanup

    @staticmethod
    def _remove_watermark(image_bytes: bytes) -> bytes:
        """Crop the bottom strip if present, then resize back.

        The watermark sits in the bottom ~6-8% of the frame. We crop it off
        and resize the remaining image back to the target square so panel
        dimensions stay consistent.
        """
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:
            return image_bytes  # not a valid image, return as-is

        w, h = img.size
        crop_ratio = 0.90  # keep top 90%, cut bottom 10% (covers full watermark strip)
        cropped = img.crop((0, 0, w, int(h * crop_ratio)))
        # Resize back to square so layout math stays correct
        resized = cropped.resize((w, h), Image.LANCZOS)

        buf = io.BytesIO()
        resized.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def generate(self, request: ImageRequest) -> ImageResult:
        prompt = self._build_prompt(request)
        seed = request.seed or random.randint(1, 10_000_000)

        last_error: Exception | None = None
        rate_limit_retries = 0
        for attempt in range(self.max_retries + 1):
            try:
                log.debug(
                    "pollinations panel=%s attempt=%d model=%s",
                    request.panel_id, attempt + 1, self.model,
                )
                image_bytes = self._fetch_image(prompt, seed + attempt * 101)
                image_bytes = self._remove_watermark(image_bytes)

                output = Path(request.output_path)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(image_bytes)
                log.info(
                    "pollinations panel=%s model=%s size=%d bytes",
                    request.panel_id, self.model, len(image_bytes),
                )
                return ImageResult(
                    path=str(output),
                    provider=self.name,
                    seed=seed,
                    meta={"model": self.model, "prompt": prompt[:300]},
                )
            except Exception as exc:
                last_error = exc
                if isinstance(exc, PollinationsRateLimitError):
                    if rate_limit_retries == 0:
                        rate_limit_retries += 1
                        log.warning(
                            "pollinations panel=%s hit the per-IP limit; "
                            "retrying after the 45s cooldown",
                            request.panel_id,
                        )
                        continue
                    break
                if attempt < self.max_retries:
                    delay = 1.5 * (2 ** attempt)
                    log.warning(
                        "pollinations panel=%s attempt %d failed: %s — retry in %.1fs",
                        request.panel_id, attempt + 1, str(exc)[:200], delay,
                    )
                    time.sleep(delay)

        # All attempts failed
        error_msg = f"Pollinations failed for panel {request.panel_id}: {last_error}"
        log.error(error_msg)
        raise ProviderError(error_msg) from last_error


def build_pollinations_image_provider() -> PollinationsImageProvider:
    return PollinationsImageProvider()
