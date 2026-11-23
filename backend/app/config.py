"""Central configuration for AI ComicVerse.

Every value comes from the environment (see ``.env.example``). Importing this
module never touches the network and never raises on a missing key, so the
application always starts - in MOCK mode if nothing is configured.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STORAGE_DIR = BACKEND_DIR / "storage"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- app ---------------------------------------------------------------
    app_name: str = "AI ComicVerse"
    environment: str = "development"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    )

    # --- storage -----------------------------------------------------------
    storage_dir: Path = DEFAULT_STORAGE_DIR

    # --- database ----------------------------------------------------------
    use_sqlite: bool = True
    database_url: str = ""
    sqlite_path: Path = BACKEND_DIR / "comicverse.db"
    postgres_user: str = "comicverse"
    postgres_password: str = "comicverse"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "comicverse"

    # --- LLM (story understanding / dialogue / camera) ---------------------
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # --- image generation --------------------------------------------------
    image_provider: str = "pollinations"
    pollinations_api_key: str = ""
    pollinations_image_edit_model: str = "openai/gpt-image-1-mini"
    gemini_image_model: str = "gemini-3.1-flash-image"
    replicate_api_token: str = ""
    replicate_model: str = "black-forest-labs/flux-kontext-pro"
    replicate_input_template: str = ""
    replicate_timeout: int = 180
    image_size: int = 768
    image_steps: int = 28
    image_guidance: float = 3.5

    # --- speech to text ----------------------------------------------------
    stt_provider: str = "mock"
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    openai_api_key: str = ""
    mock_transcript: str = ""

    # --- character memory --------------------------------------------------
    embedding_backend: str = "auto"  # auto | clip | fallback
    vector_store: str = "auto"  # auto | chroma | json
    chroma_dir: Path | None = None

    # --- continuity --------------------------------------------------------
    continuity_threshold: float = 0.62
    continuity_max_retries: int = 2
    continuity_clip_weight: float = 0.65

    # --- generation defaults ----------------------------------------------
    default_panel_count: int = 8
    panels_per_page: int = 4
    seed: int = 42

    # --- behaviour ---------------------------------------------------------
    strict_providers: bool = False

    # ------------------------------------------------------------------ util
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.use_sqlite:
            return f"sqlite:///{self.sqlite_path.as_posix()}"
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def resolved_chroma_dir(self) -> Path:
        return self.chroma_dir or (self.storage_dir / "chroma")

    @property
    def projects_dir(self) -> Path:
        return self.storage_dir / "projects"

    @property
    def refs_dir(self) -> Path:
        return self.storage_dir / "refs"

    @property
    def memory_dir(self) -> Path:
        return self.storage_dir / "memory"

    @property
    def tmp_dir(self) -> Path:
        return self.storage_dir / "tmp"

    def ensure_dirs(self) -> None:
        for path in (
            self.storage_dir,
            self.projects_dir,
            self.refs_dir,
            self.memory_dir,
            self.tmp_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def project_subdirs(self, project_id: str) -> dict[str, Path]:
        """Create and return the per-project directory layout."""
        base = self.project_dir(project_id)
        dirs = {
            "root": base,
            "refs": base / "refs",
            "panels": base / "panels",
            "pages": base / "pages",
            "exports": base / "exports",
            "memory": self.memory_dir / project_id,
        }
        for path in dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        return dirs

    def has_llm_credentials(self, provider: str | None = None) -> bool:
        provider = (provider or self.llm_provider).lower()
        if provider == "gemini":
            return bool(self.gemini_api_key.strip())
        if provider == "ollama":
            return bool(self.ollama_base_url.strip())
        return True

    def has_image_credentials(self, provider: str | None = None) -> bool:
        provider = (provider or self.image_provider).lower()
        if provider == "gemini":
            return bool(self.gemini_api_key.strip())
        if provider == "replicate":
            return bool(self.replicate_api_token.strip())
        return True

    def has_stt_credentials(self, provider: str | None = None) -> bool:
        provider = (provider or self.stt_provider).lower()
        if provider == "openai":
            return bool(self.openai_api_key.strip())
        return True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def reset_settings_cache() -> None:
    """Drop the cached Settings. Used by tests that patch the environment."""
    get_settings.cache_clear()
