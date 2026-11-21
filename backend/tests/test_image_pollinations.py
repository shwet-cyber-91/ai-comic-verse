from __future__ import annotations

import pytest

from app.providers.base import ImageRequest, ProviderError
from app.providers import image_pollinations
from app.providers.image_pollinations import (
    PollinationsImageProvider,
    PollinationsRateLimitError,
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


def test_pollinations_requests_are_spaced_by_45_seconds(monkeypatch):
    monkeypatch.setattr(image_pollinations, "_next_request_at", 0.0)
    monkeypatch.setattr(image_pollinations, "_rate_limit_until", 0.0)
    monkeypatch.setattr(image_pollinations.time, "monotonic", lambda: 100.0)
    waits = []
    monkeypatch.setattr(image_pollinations.time, "sleep", waits.append)

    image_pollinations._wait_for_request_slot()
    image_pollinations._wait_for_request_slot()

    assert waits == [45.0]


def test_pollinations_402_sets_a_45_second_cooldown(monkeypatch):
    monkeypatch.setattr(image_pollinations, "_next_request_at", 145.0)
    monkeypatch.setattr(image_pollinations, "_rate_limit_until", 0.0)
    monkeypatch.setattr(image_pollinations.time, "monotonic", lambda: 110.0)
    waits = []
    monkeypatch.setattr(image_pollinations.time, "sleep", waits.append)

    image_pollinations._defer_after_rate_limit()
    image_pollinations._wait_for_request_slot()

    assert waits == [45.0]


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
