"""SQLAlchemy persistence.

Stores the full project as a JSON payload (source of truth, so the schema can
evolve without migrations) plus normalised ``panels`` / ``characters`` rows that
make the metadata queryable - which is what the proposal asks PostgreSQL for.

Engine is chosen by ``USE_SQLITE`` / ``DATABASE_URL``: SQLite for a zero-setup
local run, PostgreSQL in docker-compose.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import get_settings
from .logging_config import get_logger
from .schemas import ComicProject, ProjectSummary

log = get_logger("db")


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    style: Mapped[str] = mapped_column(String(64), default="manga")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    language: Mapped[str] = mapped_column(String(16), default="en")
    story_text: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    panels: Mapped[list["PanelRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )
    characters: Mapped[list["CharacterRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )


class PanelRow(Base):
    __tablename__ = "panels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    panel_id: Mapped[str] = mapped_column(String(64), index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    scene_id: Mapped[str] = mapped_column(String(64), default="")
    characters: Mapped[str] = mapped_column(String(512), default="")  # comma-joined
    emotion: Mapped[str] = mapped_column(String(32), default="neutral")
    dialogue_text: Mapped[str] = mapped_column(Text, default="")
    narration: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str] = mapped_column(String(512), default="")
    continuity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    regenerations: Mapped[int] = mapped_column(Integer, default=0)
    is_edited: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[ProjectRow] = relationship(back_populates="panels")


class CharacterRow(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    role: Mapped[str] = mapped_column(String(64), default="supporting")
    appearance: Mapped[str] = mapped_column(Text, default="")
    reference_images: Mapped[str] = mapped_column(Text, default="")
    embedding_id: Mapped[str] = mapped_column(String(128), default="")
    appearance_count: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[ProjectRow] = relationship(back_populates="characters")


_engine = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.resolved_database_url
        kwargs: dict = {"future": True, "echo": False}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        try:
            _engine = create_engine(url, **kwargs)
        except Exception as exc:
            # A missing driver (PostgreSQL requested but psycopg2 absent) should
            # not stop the app: fall back to the local file and say so loudly.
            log.warning(
                "could not open %s (%s); falling back to SQLite at %s",
                url.split("://", 1)[0],
                exc,
                settings.sqlite_path,
            )
            fallback = f"sqlite:///{settings.sqlite_path.as_posix()}"
            _engine = create_engine(
                fallback, future=True, echo=False, connect_args={"check_same_thread": False}
            )
        log.info("database engine ready (%s)", _engine.url.drivername)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionFactory


def reset_engine() -> None:
    """Drop cached engine/session factory. Used by tests."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())


# --------------------------------------------------------------------------- #
# Read / write
# --------------------------------------------------------------------------- #


def save_project(project: ComicProject) -> ComicProject:
    project.updated_at = datetime.now(timezone.utc)
    payload = project.model_dump_json()

    with session_scope() as session:
        row = session.get(ProjectRow, project.project_id)
        if row is None:
            row = ProjectRow(id=project.project_id)
            session.add(row)
        row.title = project.title
        row.style = project.style
        row.status = project.status
        row.language = project.language
        row.story_text = project.story_text
        row.payload = payload
        row.updated_at = datetime.now(timezone.utc)

        session.execute(delete(PanelRow).where(PanelRow.project_id == project.project_id))
        session.execute(delete(CharacterRow).where(CharacterRow.project_id == project.project_id))

        for panel in project.panels:
            session.add(
                PanelRow(
                    project_id=project.project_id,
                    panel_id=panel.panel_id,
                    index=panel.index,
                    scene_id=panel.scene_id,
                    characters=",".join(panel.characters)[:512],
                    emotion=panel.emotion,
                    dialogue_text="\n".join(f"{d.speaker}: {d.text}" for d in panel.dialogue),
                    narration=panel.narration or "",
                    image_path=panel.image_path or "",
                    continuity_score=panel.continuity_score,
                    regenerations=panel.regenerations,
                    is_edited=1 if panel.is_edited else 0,
                )
            )
        for char in project.characters:
            session.add(
                CharacterRow(
                    project_id=project.project_id,
                    character_id=char.character_id,
                    name=char.name,
                    role=char.role,
                    appearance=char.appearance,
                    reference_images=",".join(char.reference_images),
                    embedding_id=char.embedding_id or "",
                    appearance_count=char.appearance_count,
                )
            )
    return project


def load_project(project_id: str) -> Optional[ComicProject]:
    with session_scope() as session:
        row = session.get(ProjectRow, project_id)
        if row is None:
            return None
        return ComicProject.model_validate(json.loads(row.payload))


def list_projects(limit: int = 50) -> list[ProjectSummary]:
    with session_scope() as session:
        rows = session.execute(
            select(ProjectRow).order_by(ProjectRow.updated_at.desc()).limit(limit)
        ).scalars().all()
        summaries: list[ProjectSummary] = []
        for row in rows:
            try:
                project = ComicProject.model_validate(json.loads(row.payload))
            except Exception:  # pragma: no cover - corrupt payload shouldn't kill the list
                log.warning("skipping unreadable project %s", row.id)
                continue
            summaries.append(
                ProjectSummary(
                    project_id=project.project_id,
                    title=project.title,
                    style=project.style,
                    status=project.status,
                    panel_count=len(project.panels),
                    page_count=len(project.pages),
                    character_count=len(project.characters),
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                )
            )
        return summaries


def delete_project(project_id: str) -> bool:
    with session_scope() as session:
        row = session.get(ProjectRow, project_id)
        if row is None:
            return False
        session.delete(row)
    return True


def count_projects() -> int:
    with session_scope() as session:
        return int(session.execute(select(func.count(ProjectRow.id))).scalar_one())
