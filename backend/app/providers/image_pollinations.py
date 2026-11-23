"""Pollinations.ai image generation provider.

Uses the Pollinations image API which wraps Flux/SD models. No API key is
required. Failed image requests are reported rather than replaced with mock art.

API: https://image.pollinations.ai/prompt/{url-encoded-prompt}?width=&height=&seed=&model=
Returns a PNG/JPEG directly — no polling, no auth.
"""

from __future__ import annotations

import base64
import binascii
import io
import math
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
from ..styles.presets import get_style_preset

log = get_logger("providers.image.pollinations")

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
POLLINATIONS_EDIT_URL = "https://gen.pollinations.ai/v1/images/edits"
REQUEST_INTERVAL_SECONDS = 60.0
REFERENCE_MAX_SIZE = 1024
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


def _defer_after_rate_limit(retry_after: float | None = None) -> None:
    global _next_request_at, _rate_limit_until
    if retry_after is None or not math.isfinite(retry_after) or retry_after <= 0:
        cooldown = REQUEST_INTERVAL_SECONDS
    else:
        cooldown = min(retry_after, 900.0)
    with _rate_limit_lock:
        _rate_limit_until = max(
            _rate_limit_until,
            time.monotonic() + cooldown,
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

class PollinationsImageProvider(ImageProvider):
    name = "pollinations"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        image_edit_model: str | None = None,
    ) -> None:
        settings = get_settings()
        # "flux" is the best free model; "turbo" is faster/lower quality
        self.model = model or "flux"
        self.api_key = (
            api_key if api_key is not None else settings.pollinations_api_key
        ).strip()
        self.image_edit_model = image_edit_model or settings.pollinations_image_edit_model
        self.image_size = settings.image_size or 768
        self.max_retries = 3

    @property
    def supports_reference_images(self) -> bool:
        return bool(self.api_key)

    def _build_prompt(self, request: ImageRequest) -> str:
        names = ", ".join(request.character_names) if request.character_names else "the character"
        scene = request.setting or request.action or "a dramatic scene"

        emotion = (request.emotion or "neutral").lower()
        face = EMOTION_FACES.get(emotion, f"{emotion} expression clearly on face")

        style = get_style_preset(request.style)

        character_designs = []
        for name in request.character_names:
            description = request.character_descriptions.get(name, "").strip()
            color = request.character_colors.get(name, "").strip()
            identity = description[:320]
            if color:
                identity = f"{identity}; consistent palette {color}".strip("; ")
            if identity:
                character_designs.append(f"{name}: {identity}")

        parts = [
            f"Art direction: {style.prompt_fragment}",
            f"comic panel of {names}",
            (
                "Maintain the exact same character identity, face, hair, age, body build, "
                "and outfit in every panel; character design descriptions are authoritative; "
                "do not redesign or swap characters"
            ),
            *character_designs,
            f"{request.action or 'in scene'}",
            f"facial expression: {face}",
            f"setting: {scene}",
            f"{request.shot} shot composition",
            f"{request.time_of_day} lighting",
            request.prompt or "",
            (
                "Do not use these visual traits: " + request.negative_prompt
                if request.negative_prompt
                else ""
            ),
            "high quality, detailed, expressive faces, professional comic illustration",
        ]
        return ", ".join(p for p in parts if p.strip())

    @staticmethod
    def _reference_data_uri(path: str) -> str:
        reference_path = Path(path)
        if not reference_path.is_file():
            raise ProviderError(f"reference image not found: {path}")
        try:
            with Image.open(reference_path) as source:
                image = source.convert("RGB")
                image.thumbnail((REFERENCE_MAX_SIZE, REFERENCE_MAX_SIZE), Image.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=85, optimize=True)
        except Exception as exc:
            raise ProviderError(f"could not prepare reference image {path}: {exc}") from exc
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def _fetch_reference_image(
        self,
        prompt: str,
        seed: int,
        reference_images: list[str],
        timeout: float = 180.0,
    ) -> bytes:
        readable = [path for path in reference_images if Path(path).is_file()][:4]
        if not readable:
            raise ProviderError("reference-conditioned generation needs a readable reference image")

        edit_prompt = (
            "Create a new comic panel based on the supplied character reference image(s). "
            "Preserve the referenced character identity, face, hair, age, body build, skin "
            "tone, outfit, and distinctive accessories. Do not copy the reference background. "
            "Follow the requested action, composition, setting, lighting, and art style. "
            "Do not add lettering, dialogue, captions, logos, or watermarks. "
            f"Panel description: {prompt}"
        )
        body = {
            "prompt": edit_prompt[:32000],
            "image": [
                {"image_url": self._reference_data_uri(path)}
                for path in readable
            ],
            "model": self.image_edit_model,
            "size": f"{self.image_size}x{self.image_size}",
            "quality": "medium",
            "output_format": "png",
            "response_format": "b64_json",
            "seed": seed,
        }
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    POLLINATIONS_EDIT_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Pollinations reference-image request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"Pollinations reference-image edit returned {response.status_code}: "
                f"{response.text[:300]}"
            )
        try:
            entries = response.json().get("data") or []
            encoded = entries[0].get("b64_json") if entries else None
            if not encoded:
                raise ProviderError("Pollinations reference-image response contained no image data")
            return base64.b64decode(encoded, validate=True)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, binascii.Error) as exc:
            raise ProviderError(
                f"Pollinations returned invalid reference-image data: {exc}"
            ) from exc

    def _fetch_text_image(self, prompt: str, seed: int, timeout: float = 90.0) -> bytes:
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
            if resp.status_code in (402, 429):
                try:
                    retry_after = float(resp.headers.get("retry-after", ""))
                except (TypeError, ValueError):
                    retry_after = None
                _defer_after_rate_limit(retry_after)
                raise PollinationsRateLimitError(
                    f"Pollinations returned {resp.status_code} (rate limit). "
                    "Waiting for its retry window before retrying."
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

    def _fetch_image(
        self,
        prompt: str,
        seed: int,
        reference_images: list[str] | None = None,
        timeout: float = 90.0,
    ) -> bytes:
        if self.api_key and reference_images:
            return self._fetch_reference_image(
                prompt, seed, reference_images, timeout=max(timeout, 180.0)
            )
        return self._fetch_text_image(prompt, seed, timeout)

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
                image_bytes = self._fetch_image(
                    prompt,
                    seed + attempt * 101,
                    request.reference_images,
                )
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
                            "pollinations panel=%s hit the rate limit; waiting for cooldown",
                            request.panel_id,
                        )
                        continue
                    break
                if attempt < self.max_retries:
                    delay = min(2 ** (attempt + 1), 16)
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
