"""Shared test setup.

The environment is redirected *before* any application module is imported, so the
tests never touch the developer's real database, storage folder or API keys. The
whole suite therefore runs in MOCK mode with no network access.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="comicverse-tests-"))

os.environ.update(
    {
        "STORAGE_DIR": str(_TMP / "storage"),
        "SQLITE_PATH": str(_TMP / "comicverse-test.db"),
        "USE_SQLITE": "true",
        "DATABASE_URL": "",
        "LLM_PROVIDER": "mock",
        "IMAGE_PROVIDER": "mock",
        "STT_PROVIDER": "mock",
        "EMBEDDING_BACKEND": "fallback",
        "VECTOR_STORE": "json",
        "STRICT_PROVIDERS": "false",
        "DEBUG": "false",
        "ENVIRONMENT": "test",
        "SEED": "1234",
        "IMAGE_SIZE": "256",
        "CONTINUITY_MAX_RETRIES": "2",
        "MOCK_TRANSCRIPT": "",
    }
)

# the developer's own .env must not leak into the test run
os.environ["GEMINI_API_KEY"] = ""
os.environ["REPLICATE_API_TOKEN"] = ""
os.environ["OPENAI_API_KEY"] = ""


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return _TMP


@pytest.fixture(autouse=True)
def fresh_app_state():
    """Drop every cached singleton between tests so env changes take effect."""
    from app.config import get_settings, reset_settings_cache
    from app.continuity import reset_checker
    from app.db import init_db, reset_engine
    from app.embeddings import reset_embedder
    from app.graph import reset_graphs
    from app.jobs import registry
    from app.memory import reset_memory_backend
    from app.providers.registry import reset_providers

    def _reset() -> None:
        reset_settings_cache()
        reset_engine()
        reset_providers()
        reset_memory_backend()
        reset_embedder()
        reset_checker()
        reset_graphs()
        registry.clear()

    _reset()
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    yield
    _reset()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


# --------------------------------------------------------------------------- #
# Fixtures for building inputs
# --------------------------------------------------------------------------- #

STORY = (
    "Mira the sky-courier lands her patched glider on the roof of the old "
    "observatory at dusk. The door is already open. Inside, Kestrel the astronomer "
    "is packing star charts into a cracked leather case. \"They are shutting the "
    "dome down tonight,\" she says without turning around. Mira puts the glider "
    "key on the table between them. \"Then we fly it out together,\" she answers. "
    "Outside, the first storm of the season breaks over the hills."
)


@pytest.fixture
def story_text() -> str:
    return STORY


@pytest.fixture
def reference_png() -> bytes:
    """A distinctive 128x128 portrait-ish image, used as a character reference."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (128, 128), (206, 176, 132))
    draw = ImageDraw.Draw(image)
    draw.ellipse((38, 30, 90, 88), fill=(238, 214, 186))  # face
    draw.rectangle((52, 44, 60, 52), fill=(28, 24, 30))  # eyes
    draw.rectangle((70, 44, 78, 52), fill=(28, 24, 30))
    draw.rectangle((44, 18, 86, 34), fill=(36, 30, 44))  # hair
    draw.rectangle((20, 92, 108, 128), fill=(40, 78, 120))  # shoulders

    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def stored_reference(reference_png: bytes) -> str:
    """Reference image saved the way the Create screen saves it."""
    from app.storage import save_loose_reference

    return save_loose_reference("Mira", "mira.png", reference_png)


@pytest.fixture
def story_request(stored_reference: str) -> dict:
    from app.schemas import CharacterRef, StoryRequest

    return StoryRequest(
        title="The Last Star Chart",
        story_text=STORY,
        style="manga",
        characters=[
            CharacterRef(
                name="Mira",
                description="A sky-courier in a patched flight jacket with copper goggles.",
                reference_images=[stored_reference],
            ),
            CharacterRef(
                name="Kestrel",
                description="An astronomer with grey braided hair and ink-stained sleeves.",
                reference_images=[],
            ),
        ],
        panel_count=4,
        panels_per_page=2,
        export_formats=["pdf", "web"],
    ).model_dump(mode="json")
