from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from app.providers.base import ImageRequest, ProviderError
from app.providers import image_pollinations
from app.providers.image_pollinations import (
    PollinationsImageProvider,
    PollinationsRateLimitError,
    REFERENCE_MAX_SIZE,
)


def test_pollinations_failure_does_not_generate_mock_art(monkeypatch, tmp_path):
    provider = PollinationsImageProvider()
    provider.max_retries = 0

    def fail_request(*_args, **_kwargs):
        raise ProviderError("Pollinations unavailable")

    monkeypatch.setattr(provider, "_fetch_image", fail_request)
    output_path = tmp_path / "panel.png"
    request = ImageRequest(
        panel_id="panel-1",
        prompt="A comic panel",
        output_path=str(output_path),
    )

    with pytest.raises(ProviderError, match="Pollinations failed for panel panel-1"):
        provider.generate(request)

    assert not output_path.exists()


def test_pollinations_requests_are_spaced_by_60_seconds(monkeypatch):
    monkeypatch.setattr(image_pollinations, "_next_request_at", 0.0)
    monkeypatch.setattr(image_pollinations, "_rate_limit_until", 0.0)
    monkeypatch.setattr(image_pollinations.time, "monotonic", lambda: 100.0)
    waits = []
    monkeypatch.setattr(image_pollinations.time, "sleep", waits.append)

    image_pollinations._wait_for_request_slot()
    image_pollinations._wait_for_request_slot()

    assert waits == [60.0]


def test_pollinations_402_sets_a_60_second_cooldown(monkeypatch):
    monkeypatch.setattr(image_pollinations, "_next_request_at", 145.0)
    monkeypatch.setattr(image_pollinations, "_rate_limit_until", 0.0)
    monkeypatch.setattr(image_pollinations.time, "monotonic", lambda: 110.0)
    waits = []
    monkeypatch.setattr(image_pollinations.time, "sleep", waits.append)

    image_pollinations._defer_after_rate_limit()
    image_pollinations._wait_for_request_slot()

    assert waits == [60.0]


def test_pollinations_402_retries_only_once(monkeypatch, tmp_path):
    provider = PollinationsImageProvider()
    calls = []

    def rate_limited(*_args, **_kwargs):
        calls.append(True)
        raise PollinationsRateLimitError("free-tier rate limit")

    monkeypatch.setattr(provider, "_fetch_image", rate_limited)
    monkeypatch.setattr(image_pollinations.time, "sleep", lambda _seconds: None)
    request = ImageRequest(
        panel_id="panel-1",
        prompt="A comic panel",
        output_path=str(tmp_path / "panel.png"),
    )

    with pytest.raises(ProviderError, match="Pollinations failed for panel panel-1"):
        provider.generate(request)

    assert len(calls) == 2


def test_pollinations_retries_transient_errors_with_backoff(monkeypatch, tmp_path):
    provider = PollinationsImageProvider()
    attempts = []
    waits = []

    def fail_twice(*_args, **_kwargs):
        attempts.append(True)
        if len(attempts) < 3:
            raise ProviderError("temporary network error")
        return b"generated image"

    monkeypatch.setattr(provider, "_fetch_image", fail_twice)
    monkeypatch.setattr(provider, "_remove_watermark", lambda image: image)
    monkeypatch.setattr(image_pollinations, "_wait_for_request_slot", lambda: None)
    monkeypatch.setattr(image_pollinations.time, "sleep", waits.append)
    request = ImageRequest(
        panel_id="panel-1",
        prompt="A comic panel",
        output_path=str(tmp_path / "panel.png"),
    )

    result = provider.generate(request)

    assert result.path == str(tmp_path / "panel.png")
    assert len(attempts) == 3
    assert waits == [2, 4]


def test_pollinations_429_sets_rate_limit_cooldown(monkeypatch):
    deferred = []

    class Response:
        status_code = 429
        text = "slow down"
        headers = {"retry-after": "75"}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(image_pollinations.httpx, "Client", Client)
    monkeypatch.setattr(image_pollinations, "_wait_for_request_slot", lambda: None)
    monkeypatch.setattr(image_pollinations, "_defer_after_rate_limit", deferred.append)

    provider = PollinationsImageProvider()
    with pytest.raises(PollinationsRateLimitError, match="429"):
        provider._fetch_text_image("A comic panel", 1)

    assert deferred == [75.0]


def test_pollinations_prompt_contains_fixed_character_design_and_negative_prompt():
    provider = PollinationsImageProvider()
    request = ImageRequest(
        panel_id="panel-1",
        prompt="standing on an observatory roof",
        negative_prompt="different outfit, different hair",
        character_names=["Mira"],
        character_descriptions={"Mira": "short silver hair; red flight jacket"},
        character_colors={"Mira": "#cc3344"},
    )

    prompt = provider._build_prompt(request)

    assert "short silver hair; red flight jacket" in prompt
    assert "consistent palette #cc3344" in prompt
    assert "do not redesign or swap characters" in prompt
    assert "Do not use these visual traits: different outfit, different hair" in prompt


@pytest.mark.parametrize(
    "style",
    ["manga", "anime", "manhwa", "bengali_comic", "marvel_like", "dc_like"],
)
def test_pollinations_uses_the_selected_style_without_default_manga_conflict(style):
    from app.styles.presets import get_style_preset

    provider = PollinationsImageProvider()
    request = ImageRequest(
        panel_id="panel-1",
        prompt="A character enters a room",
        style=style,
    )

    prompt = provider._build_prompt(request)
    selected_fragment = get_style_preset(style).prompt_fragment

    assert selected_fragment in prompt
    if style != "manga":
        assert "Art direction: manga style" not in prompt


def test_reference_support_requires_a_pollinations_api_key():
    assert PollinationsImageProvider(api_key="").supports_reference_images is False
    assert PollinationsImageProvider(api_key="test-key").supports_reference_images is True


def test_reference_edit_sends_images_and_decodes_result(monkeypatch, tmp_path):
    source_path = tmp_path / "reference.png"
    Image.new("RGB", (1600, 1200), (180, 90, 50)).save(source_path)
    generated_buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (20, 40, 60)).save(generated_buffer, format="PNG")
    generated = generated_buffer.getvalue()
    calls = {}

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(generated).decode("ascii")}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def post(self, url, **kwargs):
            calls["url"] = url
            calls.update(kwargs)
            return Response()

    monkeypatch.setattr(image_pollinations.httpx, "Client", Client)
    provider = PollinationsImageProvider(api_key="test-key")

    result = provider._fetch_image("Mira in a red jacket", 17, [str(source_path)])

    assert result == generated
    assert calls["url"] == image_pollinations.POLLINATIONS_EDIT_URL
    assert calls["headers"]["Authorization"] == "Bearer test-key"
    assert calls["json"]["model"] == "openai/gpt-image-1-mini"
    image_uri = calls["json"]["image"][0]["image_url"]
    assert image_uri.startswith("data:image/jpeg;base64,")
    decoded_reference = base64.b64decode(image_uri.split(",", 1)[1])
    with Image.open(io.BytesIO(decoded_reference)) as reference:
        assert reference.size == (REFERENCE_MAX_SIZE, 768)
