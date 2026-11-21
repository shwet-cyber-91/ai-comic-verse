"""Speech to text: local faster-whisper, or the OpenAI transcription API.

``faster_whisper`` is an optional extra (see requirements-extras.txt). When it is
not installed, ``available()`` returns False and the registry substitutes the
mock provider rather than crashing the voice feature.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ..config import get_settings
from ..logging_config import get_logger
from .base import ProviderError, STTProvider, TranscriptResult

log = get_logger("providers.stt.whisper")

_MODEL_CACHE: dict[str, object] = {}


def faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    return True


class FasterWhisperSTT(STTProvider):
    name = "faster_whisper"

    def __init__(self, model_size: str | None = None, device: str | None = None) -> None:
        settings = get_settings()
        self.model_size = model_size or settings.whisper_model
        self.device = device or settings.whisper_device
        if not faster_whisper_available():
            raise ProviderError(
                "faster-whisper is not installed. Install the optional extra "
                "(`pip install faster-whisper`) or set STT_PROVIDER=mock."
            )

    def _model(self):
        from faster_whisper import WhisperModel

        key = f"{self.model_size}:{self.device}"
        if key not in _MODEL_CACHE:
            log.info("loading faster-whisper model %s on %s (first call downloads it)", self.model_size, self.device)
            compute_type = "int8" if self.device == "cpu" else "float16"
            _MODEL_CACHE[key] = WhisperModel(self.model_size, device=self.device, compute_type=compute_type)
        return _MODEL_CACHE[key]

    def transcribe(self, audio_path: str) -> TranscriptResult:
        path = Path(audio_path)
        if not path.exists():
            raise ProviderError(f"audio file not found: {audio_path}")
        model = self._model()
        try:
            segments, info = model.transcribe(str(path), beam_size=5, vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:
            raise ProviderError(f"whisper transcription failed: {exc}") from exc
        return TranscriptResult(
            text=text,
            provider=f"{self.name}:{self.model_size}",
            language=getattr(info, "language", "en") or "en",
            duration=getattr(info, "duration", None),
        )


class OpenAIWhisperSTT(STTProvider):
    name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self.api_key = (api_key if api_key is not None else settings.openai_api_key).strip()
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not set")

    def transcribe(self, audio_path: str) -> TranscriptResult:
        path = Path(audio_path)
        if not path.exists():
            raise ProviderError(f"audio file not found: {audio_path}")
        try:
            with httpx.Client(timeout=300.0) as client:
                with path.open("rb") as handle:
                    response = client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        files={"file": (path.name, handle, "application/octet-stream")},
                        data={"model": "whisper-1", "response_format": "verbose_json"},
                    )
        except httpx.HTTPError as exc:
            raise ProviderError(f"transcription request failed: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderError(f"transcription API returned {response.status_code}: {response.text[:300]}")
        payload = response.json()
        return TranscriptResult(
            text=(payload.get("text") or "").strip(),
            provider=self.name,
            language=payload.get("language", "en") or "en",
            duration=payload.get("duration"),
        )


def build_faster_whisper_stt() -> FasterWhisperSTT:
    return FasterWhisperSTT()


def build_openai_whisper_stt() -> OpenAIWhisperSTT:
    return OpenAIWhisperSTT()
