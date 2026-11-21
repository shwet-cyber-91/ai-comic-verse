"""FLUX (and friends) with reference-image conditioning, via Replicate.

Covers the three conditioning families named in the brief:
  * FLUX Kontext      - `input_image` + an edit-style prompt
  * IP-Adapter FLUX   - `image` as a style/identity adapter input
  * PuLID             - `image` as an identity input

Each expects different input keys, so the mapping is data, not code: pick a
built-in template by model name, or set REPLICATE_INPUT_TEMPLATE to any JSON
object using the placeholders {prompt} {negative_prompt} {image} {seed}
{aspect_ratio} {steps} {guidance}.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings
from ..logging_config import get_logger
from .base import ImageProvider, ImageRequest, ImageResult, ProviderError

log = get_logger("providers.image.replicate")

API_BASE = "https://api.replicate.com/v1"

# model-name substring -> input template
BUILTIN_TEMPLATES: list[tuple[str, dict[str, Any]]] = [
    (
        "kontext",
        {
            "prompt": "{prompt}",
            "input_image": "{image}",
            "aspect_ratio": "{aspect_ratio}",
            "output_format": "png",
            "safety_tolerance": 2,
        },
    ),
    (
        "pulid",
        {
            "prompt": "{prompt}",
            "image": "{image}",
            "num_inference_steps": "{steps}",
            "guidance_scale": "{guidance}",
            "seed": "{seed}",
            "output_format": "png",
        },
    ),
    (
        "ip-adapter",
        {
            "prompt": "{prompt}",
            "image": "{image}",
            "num_inference_steps": "{steps}",
            "guidance_scale": "{guidance}",
            "seed": "{seed}",
            "output_format": "png",
        },
    ),
    (
        "",
        {
            "prompt": "{prompt}",
            "image": "{image}",
            "num_outputs": 1,
            "output_format": "png",
        },
    ),
]


def _data_uri(path: str) -> str:
    file_path = Path(path)
    if not file_path.exists():
        raise ProviderError(f"reference image not found: {path}")
    mime = mimetypes.guess_type(file_path.name)[0] or "image/png"
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


class ReplicateImageProvider(ImageProvider):
    name = "replicate"

    def __init__(self, api_token: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_token = (api_token if api_token is not None else settings.replicate_api_token).strip()
        self.model = (model or settings.replicate_model).strip()
        self.timeout = settings.replicate_timeout
        self.size = settings.image_size
        self.steps = settings.image_steps
        self.guidance = settings.image_guidance
        self.template_override = settings.replicate_input_template.strip()
        if not self.api_token:
            raise ProviderError("REPLICATE_API_TOKEN is not set")
        if not self.model:
            raise ProviderError("REPLICATE_MODEL is not set")

    @property
    def supports_reference_images(self) -> bool:
        return True

    # -- request building --------------------------------------------------
    def _template(self) -> dict[str, Any]:
        if self.template_override:
            try:
                parsed = json.loads(self.template_override)
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    f"REPLICATE_INPUT_TEMPLATE is not valid JSON: {exc}"
                ) from exc
            if not isinstance(parsed, dict):
                raise ProviderError("REPLICATE_INPUT_TEMPLATE must be a JSON object")
            return parsed
        lowered = self.model.lower()
        for needle, template in BUILTIN_TEMPLATES:
            if needle in lowered:
                return template
        return BUILTIN_TEMPLATES[-1][1]

    def _render_template(self, value: Any, mapping: dict[str, str]) -> Any:
        if isinstance(value, str):
            for key, replacement in mapping.items():
                value = value.replace("{" + key + "}", str(replacement))
            return value
        if isinstance(value, dict):
            return {k: self._render_template(v, mapping) for k, v in value.items()}
        if isinstance(value, list):
            return [self._render_template(v, mapping) for v in value]
        return value

    def _build_input(self, request: ImageRequest) -> dict[str, Any]:
        reference = next((p for p in request.reference_images if Path(p).exists()), None)
        mapping = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "image": _data_uri(reference) if reference else "",
            "seed": request.seed,
            "aspect_ratio": "1:1",
            "steps": self.steps,
            "guidance": self.guidance,
        }
        payload = self._render_template(self._template(), mapping)
        if not reference:
            # no reference available: drop conditioning keys rather than send ""
            payload = {k: v for k, v in payload.items() if v != "" and k not in ("input_image", "image")}
            log.warning(
                "panel %s has no readable reference image - falling back to text-to-image",
                request.panel_id,
            )
        return payload

    # -- HTTP --------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Prefer": "wait=60",
        }

    def generate(self, request: ImageRequest) -> ImageResult:
        payload = self._build_input(request)
        if "/" in self.model:
            url = f"{API_BASE}/models/{self.model}/predictions"
            body: dict[str, Any] = {"input": payload}
        else:  # a bare version hash
            url = f"{API_BASE}/predictions"
            body = {"version": self.model, "input": payload}

        log.info("replicate: %s (%d input keys)", self.model, len(payload))
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, headers=self._headers(), json=body)
                if response.status_code >= 400:
                    raise ProviderError(
                        f"replicate rejected the request ({response.status_code}): {response.text[:500]}"
                    )
                prediction = response.json()
                prediction = self._poll(client, prediction)
        except httpx.HTTPError as exc:
            raise ProviderError(f"replicate request failed: {exc}") from exc

        image_url = self._extract_output_url(prediction)
        output_path = Path(request.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                image_response = client.get(image_url)
                image_response.raise_for_status()
                output_path.write_bytes(image_response.content)
        except httpx.HTTPError as exc:
            raise ProviderError(f"could not download generated image: {exc}") from exc

        return ImageResult(
            path=str(output_path),
            provider=self.name,
            seed=request.seed,
            meta={
                "model": self.model,
                "prediction_id": prediction.get("id"),
                "input_keys": sorted(payload.keys()),
            },
        )

    def _poll(self, client: httpx.Client, prediction: dict[str, Any], interval: float = 1.5) -> dict[str, Any]:
        deadline = time.time() + self.timeout
        get_url = (prediction.get("urls") or {}).get("get")
        while prediction.get("status") in ("starting", "processing"):
            if time.time() > deadline:
                raise ProviderError(
                    f"replicate prediction {prediction.get('id')} timed out after {self.timeout}s"
                )
            if not get_url:
                raise ProviderError("replicate did not return a polling URL")
            time.sleep(interval)
            response = client.get(get_url, headers=self._headers())
            if response.status_code >= 400:
                raise ProviderError(
                    f"replicate polling failed ({response.status_code}): {response.text[:300]}"
                )
            prediction = response.json()
            log.debug("replicate status=%s", prediction.get("status"))

        if prediction.get("status") != "succeeded":
            raise ProviderError(
                f"replicate prediction {prediction.get('status')}: {prediction.get('error')}"
            )
        return prediction

    def _extract_output_url(self, prediction: dict[str, Any]) -> str:
        output = prediction.get("output")
        if isinstance(output, list):
            output = output[0] if output else None
        if isinstance(output, dict):
            output = output.get("url") or output.get("image")
        if not output or not isinstance(output, str):
            raise ProviderError(f"could not find an image URL in the prediction output: {output!r}")
        return output


def build_replicate_image_provider() -> ReplicateImageProvider:
    return ReplicateImageProvider()
