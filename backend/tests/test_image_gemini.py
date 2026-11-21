from __future__ import annotations

from pathlib import Path

from app.config import get_settings, reset_settings_cache
from app.providers.base import ImageRequest
from app.providers.registry import get_image_provider, reset_providers


class FakeGeminiModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self._build_response()

    def _build_response(self):
        class FakeInlineData:
            def __init__(self):
                self.data = b"fakepngbytes"
                self.mime_type = "image/png"

        class FakePart:
            def __init__(self):
                self.inline_data = FakeInlineData()

        class FakeContent:
            def __init__(self):
                self.parts = [FakePart()]

        class FakeCandidate:
            def __init__(self):
                self.content = FakeContent()

        class FakeResponse:
            def __init__(self):
                self.candidates = [FakeCandidate()]

        return FakeResponse()


class FakeGeminiClient:
    def __init__(self, *args, **kwargs):
        self.models = FakeGeminiModels()


def test_image_provider_selection_uses_gemini_when_configured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    reset_settings_cache()
    reset_providers()

    provider = get_image_provider()
    assert provider.name == "gemini"

    reset_providers()
    reset_settings_cache()


def test_gemini_image_request_includes_reference_images(monkeypatch, tmp_path):
    from app.providers.image_gemini import GeminiImageProvider

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    reset_settings_cache()
    reset_providers()

    ref_a = tmp_path / "a.png"
    ref_b = tmp_path / "b.png"
    ref_a.write_bytes(b"A")
    ref_b.write_bytes(b"B")

    monkeypatch.setattr("app.providers.image_gemini.genai.Client", FakeGeminiClient)
    provider = GeminiImageProvider()
    request = ImageRequest(
        panel_id="p001",
        prompt="A dramatic scene",
        style="manga",
        output_path=str(tmp_path / "out.png"),
        reference_images=[str(ref_a), str(ref_b)],
        character_names=["Mira", "Kestrel"],
        action="Mira looks across the room",
        emotion="anger",
        shot="wide",
        setting="roof at dusk",
        time_of_day="dusk",
    )

    result = provider.generate(request)
    assert result.provider == "gemini"
    assert Path(result.path).exists()
    assert len(provider.client.models.calls[0]["contents"]) >= 3
    assert any(
        getattr(getattr(part, "inline_data", None), "mime_type", "") == "image/png"
        for part in provider.client.models.calls[0]["contents"]
    )

    reset_providers()
    reset_settings_cache()


def test_gemini_retries_on_429_and_eventually_succeeds(monkeypatch, tmp_path):
    from app.providers import image_gemini
    from app.providers.image_gemini import GeminiImageProvider

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    reset_settings_cache()

    calls = {"count": 0}

    class FakeRetryResponse:
        @staticmethod
        def candidates_response():
            class FakeInlineData:
                data = b"retrypng"
                mime_type = "image/png"

            class FakePart:
                def __init__(self):
                    self.inline_data = FakeInlineData()

            class FakeContent:
                def __init__(self):
                    self.parts = [FakePart()]

            class FakeCandidate:
                def __init__(self):
                    self.content = FakeContent()

            class FakeResponse:
                def __init__(self):
                    self.candidates = [FakeCandidate()]

            return FakeResponse()

    def fake_generate(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("429 Too Many Requests")
        return FakeRetryResponse.candidates_response()

    monkeypatch.setattr(image_gemini.genai, "Client", lambda **kwargs: type("C", (), {"models": type("M", (), {"generate_content": staticmethod(fake_generate)})()})())
    provider = GeminiImageProvider()
    request = ImageRequest(
        panel_id="p002",
        prompt="Retry test",
        output_path=str(tmp_path / "retry.png"),
    )
    result = provider.generate(request)
    assert result.provider == "gemini"
    assert calls["count"] == 2


def test_gemini_falls_back_to_mock_when_response_is_empty(monkeypatch, tmp_path):
    from app.providers import image_gemini
    from app.providers.image_gemini import GeminiImageProvider
    from app.providers.image_mock import MockImageProvider

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("STRICT_PROVIDERS", "false")
    reset_settings_cache()

    class FakeEmptyResponse:
        candidates = []

    def fake_generate(**kwargs):
        return FakeEmptyResponse()

    monkeypatch.setattr(image_gemini.genai, "Client", lambda **kwargs: type("C", (), {"models": type("M", (), {"generate_content": staticmethod(fake_generate)})()})())
    provider = GeminiImageProvider()
    request = ImageRequest(
        panel_id="p003",
        prompt="No image returned",
        output_path=str(tmp_path / "empty.png"),
    )

    result = provider.generate(request)
    assert result.provider == "mock"
    assert isinstance(result, type(MockImageProvider().generate(request)))
