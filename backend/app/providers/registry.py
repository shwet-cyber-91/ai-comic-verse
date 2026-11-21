"""Provider selection.

Reads the configuration, tries to build the requested provider, and falls back to
mock (with a loud log line) when it cannot be constructed. ``STRICT_PROVIDERS=true``
turns that fallback into a hard error instead.

The effective choices are exposed through ``provider_info()`` and surfaced in
``GET /api/health`` and in the frontend banner, so it is never ambiguous whether
you are looking at real output or mock output.
"""

from __future__ import annotations

import threading
from typing import Optional

from ..config import get_settings
from ..logging_config import get_logger
from ..schemas import ProviderInfo
from .base import ImageProvider, LLMProvider, ProviderError, STTProvider
from .image_mock import MockImageProvider
from .llm_mock import MockLLM
from .stt_mock import MockSTTProvider

log = get_logger("providers.registry")

_lock = threading.RLock()
_llm: Optional[LLMProvider] = None
_image: Optional[ImageProvider] = None
_stt: Optional[STTProvider] = None
_fallbacks: dict[str, bool] = {"llm": False, "image": False, "stt": False}


def _handle_failure(kind: str, requested: str, error: Exception) -> None:
    settings = get_settings()
    _fallbacks[kind] = True
    no_image_fallback = (
        kind == "image" and requested in {"pollinations", "pollination", "free"}
    )
    message = f"{kind} provider '{requested}' is unavailable ({error})"
    if settings.strict_providers or no_image_fallback:
        message += "; refusing to substitute mock artwork"
        raise ProviderError(message) from error
    message += "; falling back to the built-in mock provider"
    log.warning(message)


def get_llm() -> LLMProvider:
    global _llm
    with _lock:
        if _llm is not None:
            return _llm

        settings = get_settings()
        requested = (settings.llm_provider or "mock").lower()

        if requested == "mock":
            _llm = MockLLM(seed=settings.seed)
        elif requested == "gemini":
            try:
                from .llm_gemini import build_gemini_llm

                _llm = build_gemini_llm()
            except Exception as exc:
                _handle_failure("llm", requested, exc)
                _llm = MockLLM(seed=settings.seed)
        elif requested == "ollama":
            try:
                from .llm_ollama import build_ollama_llm

                _llm = build_ollama_llm()
            except Exception as exc:
                _handle_failure("llm", requested, exc)
                _llm = MockLLM(seed=settings.seed)
        else:
            _handle_failure("llm", requested, ValueError(f"unknown provider '{requested}'"))
            _llm = MockLLM(seed=settings.seed)

        log.info("LLM provider: %s", _llm.name)
        return _llm


def get_image_provider() -> ImageProvider:
    global _image
    with _lock:
        if _image is not None:
            return _image

        settings = get_settings()
        requested = (settings.image_provider or "mock").lower()

        if requested == "mock":
            _image = MockImageProvider()
        elif requested in ("gemini",):
            try:
                from .image_gemini import build_gemini_image_provider

                _image = build_gemini_image_provider()
            except Exception as exc:
                _handle_failure("image", requested, exc)
                _image = MockImageProvider()
        elif requested in ("replicate", "flux", "fal"):
            try:
                from .image_replicate import build_replicate_image_provider

                _image = build_replicate_image_provider()
            except Exception as exc:
                _handle_failure("image", requested, exc)
                _image = MockImageProvider()
        elif requested in ("pollinations", "pollination", "free"):
            try:
                from .image_pollinations import build_pollinations_image_provider

                _image = build_pollinations_image_provider()
            except Exception as exc:
                _handle_failure("image", requested, exc)
                _image = MockImageProvider()
        else:
            _handle_failure("image", requested, ValueError(f"unknown provider '{requested}'"))
            _image = MockImageProvider()

        log.info(
            "image provider: %s (reference conditioning: %s)",
            _image.name,
            "yes" if _image.supports_reference_images else "no",
        )
        return _image


def get_stt() -> STTProvider:
    global _stt
    with _lock:
        if _stt is not None:
            return _stt

        settings = get_settings()
        requested = (settings.stt_provider or "mock").lower()

        if requested == "mock":
            _stt = MockSTTProvider()
        elif requested in ("faster_whisper", "whisper", "whisper_local"):
            try:
                from .stt_whisper import build_faster_whisper_stt

                _stt = build_faster_whisper_stt()
            except Exception as exc:
                _handle_failure("stt", requested, exc)
                _stt = MockSTTProvider()
        elif requested == "openai":
            try:
                from .stt_whisper import build_openai_whisper_stt

                _stt = build_openai_whisper_stt()
            except Exception as exc:
                _handle_failure("stt", requested, exc)
                _stt = MockSTTProvider()
        else:
            _handle_failure("stt", requested, ValueError(f"unknown provider '{requested}'"))
            _stt = MockSTTProvider()

        log.info("STT provider: %s", _stt.name)
        return _stt


def provider_info() -> ProviderInfo:
    from ..embeddings import embedder_name
    from ..memory import memory_backend_name

    llm = get_llm()
    image = get_image_provider()
    stt = get_stt()
    return ProviderInfo(
        llm=llm.name,
        image=image.name,
        stt=stt.name,
        embedding=embedder_name(),
        vector_store=memory_backend_name(),
        llm_fallback=_fallbacks["llm"],
        image_fallback=_fallbacks["image"],
        stt_fallback=_fallbacks["stt"],
    )


def is_mock_mode() -> bool:
    info = provider_info()
    return info.llm == "mock" and info.image == "mock"


def reset_providers() -> None:
    """Drop cached providers. Used by tests and after a settings change."""
    global _llm, _image, _stt
    with _lock:
        _llm = None
        _image = None
        _stt = None
        _fallbacks.update({"llm": False, "image": False, "stt": False})
