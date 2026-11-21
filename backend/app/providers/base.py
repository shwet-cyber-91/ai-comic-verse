"""Provider interfaces.

Three families, each with a mock implementation so the whole system runs with
no keys and no GPU:

  * ``LLMProvider``   - story understanding, dialogue, camera, prompts
  * ``ImageProvider`` - panel rendering (mock, or FLUX behind a reference-image API)
  * ``STTProvider``   - voice to text

``BaseLLM`` owns the JSON contract for every LLM-backed node: build a
schema-driven prompt, call the provider, extract JSON, validate with Pydantic,
and retry exactly once with a repair instruction before giving up.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

from ..logging_config import get_logger

log = get_logger("providers")

ModelT = TypeVar("ModelT", bound=BaseModel)


class ProviderError(RuntimeError):
    """Raised when a provider cannot fulfil a request (bad JSON, HTTP error, ...)."""


# --------------------------------------------------------------------------- #
# JSON helpers
# --------------------------------------------------------------------------- #


def extract_json(raw: str) -> Any:
    """Pull the first JSON object/array out of a model response.

    Handles fenced code blocks and prose preamble, which every real model
    produces sooner or later.
    """
    if raw is None:
        raise ProviderError("empty response from model")
    text = raw.strip()
    if not text:
        raise ProviderError("empty response from model")

    text = re.sub(r"^```[a-zA-Z0-9_+-]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(f"malformed JSON in response: {exc}") from exc
    raise ProviderError("no JSON object found in model response")


REPAIR_SYSTEM = (
    "You fix malformed JSON. Reply with ONLY a single valid JSON value that "
    "matches the requested schema. No prose, no markdown fences, no comments."
)


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #


@dataclass
class ImageRequest:
    """Everything an image provider needs to render one panel."""

    panel_id: str
    prompt: str
    negative_prompt: str = ""
    style: str = "manga"
    size: int = 768
    seed: int = 0
    output_path: str = ""
    reference_images: list[str] = field(default_factory=list)  # absolute paths
    character_names: list[str] = field(default_factory=list)
    character_colors: dict[str, str] = field(default_factory=dict)
    action: str = ""
    emotion: str = "neutral"
    shot: str = "medium"
    setting: str = ""
    time_of_day: str = "day"
    dialogue_hint: str = ""


@dataclass
class ImageResult:
    path: str
    provider: str
    seed: int
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class TranscriptResult:
    text: str
    provider: str
    language: str = "en"
    duration: float | None = None


class LLMProvider(ABC):
    name: str = "llm"

    @abstractmethod
    def complete_json(self, task: str, payload: dict[str, Any], schema: Type[ModelT]) -> ModelT:
        """Run one named task and return a validated instance of ``schema``."""

    @abstractmethod
    def _generate(self, system: str, user: str) -> str:
        """Raw text completion. Implemented per backend."""

    def complete_text(self, system: str, user: str) -> str:
        return self._generate(system, user)


class BaseLLM(LLMProvider):
    """Shared JSON discipline: validate, and on failure retry once with a repair prompt."""

    name = "base"
    max_json_retries = 1

    def _raw_for_task(
        self, task: str, payload: dict[str, Any], system: str, user: str
    ) -> str:
        """Raw response for a task. Overridden by the mock provider, which does
        not need a prompt at all - but still returns a JSON *string* so that the
        validation and retry path below is the same code that ships."""
        return self._generate(system, user)

    def complete_json(self, task: str, payload: dict[str, Any], schema: Type[ModelT]) -> ModelT:
        from .prompts import build_prompt

        system, user = build_prompt(task, payload, schema)
        last_error: Exception | None = None
        raw = ""

        for attempt in range(self.max_json_retries + 1):
            if attempt == 0:
                raw = self._raw_for_task(task, payload, system, user)
            else:
                repair_user = (
                    f"Your previous reply was not valid JSON for the requested schema.\n"
                    f"Error: {last_error}\n\n"
                    f"Schema:\n{json.dumps(schema.model_json_schema(), indent=2)}\n\n"
                    f"Previous reply:\n{raw[:2000]}\n\n"
                    f"Return ONLY corrected JSON."
                )
                raw = self._generate(REPAIR_SYSTEM, repair_user)
            try:
                data = extract_json(raw)
                return schema.model_validate(data)
            except (ProviderError, ValidationError, ValueError) as exc:
                last_error = exc
                log.warning(
                    "%s task=%r attempt %d/%d invalid JSON: %s",
                    self.name,
                    task,
                    attempt + 1,
                    self.max_json_retries + 1,
                    str(exc).splitlines()[0][:200],
                )

        raise ProviderError(
            f"{self.name} returned invalid JSON for task '{task}' after "
            f"{self.max_json_retries + 1} attempts: {last_error}"
        )

    def _generate(self, system: str, user: str) -> str:  # pragma: no cover - abstract in practice
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Image
# --------------------------------------------------------------------------- #


class ImageProvider(ABC):
    name: str = "image"

    @abstractmethod
    def generate(self, request: ImageRequest) -> ImageResult:
        """Render one panel and return the path it was written to."""

    @property
    def supports_reference_images(self) -> bool:
        return False


# --------------------------------------------------------------------------- #
# Speech to text
# --------------------------------------------------------------------------- #


class STTProvider(ABC):
    name: str = "stt"

    @abstractmethod
    def transcribe(self, audio_path: str) -> TranscriptResult:
        """Transcribe an audio file to text."""
