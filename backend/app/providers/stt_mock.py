"""Mock speech-to-text.

If a ``<audio>.txt`` sidecar exists next to the upload, its contents are used
(handy for tests and demos). Otherwise the configured MOCK_TRANSCRIPT is used,
or a built-in demo story is returned so the voice path is demonstrable without
any model.
"""

from __future__ import annotations

from pathlib import Path

from ..config import get_settings
from ..logging_config import get_logger
from .base import STTProvider, TranscriptResult

log = get_logger("providers.stt.mock")

DEFAULT_TRANSCRIPT = (
    "Maya had not slept. The letter from the coast arrived three days late, and the "
    "seal was already broken. She read it twice on the staircase, then once more in "
    "the kitchen with the light off. By morning she had packed a single bag, left the "
    "key under the flowerpot, and started walking toward the harbour. The bus did not "
    "come. She did not wait for it. At the dock, an old man in a grey coat was "
    "mending a net, and he did not look up when she asked about the boat. He said the "
    "boat had not sailed in eleven years. Maya sat down on the crate beside him and "
    "said she had time. The old man laughed, finally, and told her the truth about "
    "her brother. A storm was coming in from the east. They would need to leave before "
    "the tide turned."
)


class MockSTTProvider(STTProvider):
    name = "mock"

    def transcribe(self, audio_path: str) -> TranscriptResult:
        settings = get_settings()
        path = Path(audio_path)

        sidecar = path.with_suffix(".txt")
        if sidecar.exists():
            text = sidecar.read_text(encoding="utf-8", errors="replace").strip()
            log.info("mock STT used sidecar %s", sidecar.name)
            return TranscriptResult(text=text, provider=f"{self.name}:sidecar")

        if settings.mock_transcript.strip():
            return TranscriptResult(text=settings.mock_transcript.strip(), provider=f"{self.name}:env")

        log.info("mock STT returned the built-in demo transcript")
        return TranscriptResult(text=DEFAULT_TRANSCRIPT, provider=f"{self.name}:demo")


def build_mock_stt_provider() -> MockSTTProvider:
    return MockSTTProvider()
