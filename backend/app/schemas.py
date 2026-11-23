"""Pydantic models: the single contract shared by the graph nodes, the API and
the frontend.

Naming rules used throughout:
  * ``*Request``  - inbound API payload
  * ``*Plan``     - strict-JSON output of exactly one LLM task
  * ``Panel`` / ``PageLayout`` / ``CharacterSheet`` / ``ComicProject`` - persisted state
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Literals
# --------------------------------------------------------------------------- #

StyleName = Literal[
    "manga", "anime", "manhwa", "bengali_comic", "marvel_like", "dc_like"
]

ShotType = Literal[
    "establishing_wide",
    "wide",
    "medium",
    "medium_close",
    "close_up",
    "extreme_close_up",
    "over_the_shoulder",
    "low_angle",
    "high_angle",
    "bird_eye",
    "dutch_angle",
]

BubbleKind = Literal[
    "speech", "thought", "shout", "whisper", "narration", "caption", "sfx"
]

Emotion = Literal[
    "neutral",
    "joy",
    "sadness",
    "anger",
    "fear",
    "surprise",
    "disgust",
    "determination",
    "love",
    "confusion",
]

ExportFormat = Literal["pdf", "png_zip", "web", "epub"]

ProjectStatus = Literal["draft", "queued", "running", "ready", "failed"]

JobStatusName = Literal["queued", "running", "succeeded", "failed"]

LayoutTemplate = Literal[
    "splash",
    "two_horizontal",
    "two_vertical",
    "three_strip",
    "hero_top",
    "hero_left",
    "hero_five",
    "grid_2x2",
    "grid_2x3",
    "grid_3x2",
    "grid_3x3",
    "auto_grid",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


class CharacterRef(_Base):
    """A character supplied by the user, with 1-2 reference images."""

    name: str = Field(min_length=1)
    description: str = ""
    reference_images: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        v = re.sub(r"'s$", "", v, flags=re.IGNORECASE)
        v = " ".join(v.split())
        if not v:
            raise ValueError("character name must not be blank")
        return v


class StoryRequest(_Base):
    title: str = "Untitled Comic"
    story_text: str = Field(min_length=1)
    style: StyleName = "manga"
    characters: list[CharacterRef] = Field(default_factory=list)
    panel_count: int = Field(default=8, ge=2, le=40)
    auto_panel_count: bool = False
    panels_per_page: int = Field(default=4, ge=1, le=9)
    language: str = "en"
    export_formats: list[ExportFormat] = Field(
        default_factory=lambda: ["pdf", "png_zip", "web", "epub"]
    )
    continuity_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    seed: Optional[int] = None

    @field_validator("story_text")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("story_text must not be blank")
        return v


class PanelUpdateRequest(_Base):
    """Editor payload. Every field is optional - only what is sent is changed."""

    dialogue: Optional[list["DialogueLine"]] = None
    narration: Optional[str] = None
    sfx: Optional[str] = None
    action: Optional[str] = None
    scene_summary: Optional[str] = None
    emotion: Optional[str] = None
    expression: Optional[str] = None
    characters: Optional[list[str]] = None


class RegeneratePanelRequest(_Base):
    seed: Optional[int] = None
    prompt_override: Optional[str] = None


class TranscribeResponse(_Base):
    text: str
    language: str = "en"
    provider: str
    duration: Optional[float] = None


class ExportRequest(_Base):
    formats: list[ExportFormat] = Field(default_factory=lambda: ["pdf", "png_zip", "web", "epub"])


class LayoutRequest(_Base):
    template: Optional[LayoutTemplate] = None
    panels_per_page: Optional[int] = Field(default=None, ge=1, le=9)


# --------------------------------------------------------------------------- #
# LLM task outputs (strict JSON)
# --------------------------------------------------------------------------- #


class CharacterDraft(_Base):
    name: str
    role: str = "supporting"
    appearance: str = ""
    personality: str = ""
    importance: int = Field(default=3, ge=1, le=5)


class StoryAnalysis(_Base):
    title: str
    logline: str
    genre: str = "drama"
    tone: str = "neutral"
    setting: str = ""
    time_period: str = "present day"
    themes: list[str] = Field(default_factory=list)
    characters: list[CharacterDraft] = Field(default_factory=list)
    scene_count: int = Field(default=3, ge=1, le=8)
    recommended_panel_count: int = Field(ge=2, le=24)
    narrative_arc: list[str] = Field(default_factory=list)


class ScenePlan(_Base):
    scene_id: str
    index: int
    title: str
    summary: str
    setting: str
    time_of_day: str = "day"
    characters: list[str] = Field(default_factory=list)
    action: str = ""
    mood: str = "neutral"
    beats: list[str] = Field(default_factory=list)


class ScenePlanList(_Base):
    scenes: list[ScenePlan] = Field(default_factory=list)

    @field_validator("scenes")
    @classmethod
    def _non_empty(cls, v: list[ScenePlan]) -> list[ScenePlan]:
        if not v:
            raise ValueError("at least one scene is required")
        return v


class CharacterSheetDraft(_Base):
    name: str
    role: str = "supporting"
    appearance: str = ""
    outfit: str = ""
    personality: str = ""
    distinguishing_features: list[str] = Field(default_factory=list)
    palette: list[str] = Field(default_factory=list)
    signature_props: list[str] = Field(default_factory=list)


class CharacterSheetPlan(_Base):
    characters: list[CharacterSheetDraft] = Field(default_factory=list)


class BeatEmotion(_Base):
    panel_id: str
    emotion: Emotion = "neutral"
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    expression: str = ""


class EmotionPlan(_Base):
    beats: list[BeatEmotion] = Field(default_factory=list)


class BubblePosition(_Base):
    """Bubble center as normalized coordinates within its panel."""

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class DialogueLine(_Base):
    speaker: str = "Narrator"
    text: str = ""
    kind: BubbleKind = "speech"
    emotion: Emotion = "neutral"
    position: Optional[BubblePosition] = None


class PanelDialogue(_Base):
    panel_id: str
    lines: list[DialogueLine] = Field(default_factory=list)
    narration: Optional[str] = None
    sfx: Optional[str] = None


class DialoguePlan(_Base):
    panels: list[PanelDialogue] = Field(default_factory=list)


class CameraSpec(_Base):
    shot: ShotType = "medium"
    angle_notes: str = ""
    lens: str = "35mm"
    composition: str = ""
    movement: str = "static"
    rationale: str = ""


class PanelCamera(_Base):
    panel_id: str
    camera: CameraSpec


class CameraPlan(_Base):
    panels: list[PanelCamera] = Field(default_factory=list)


class PanelPrompt(_Base):
    panel_id: str
    positive: str
    negative: str = ""


class PromptPlan(_Base):
    panels: list[PanelPrompt] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Persisted entities
# --------------------------------------------------------------------------- #


class CharacterSheet(_Base):
    character_id: str
    name: str
    role: str = "supporting"
    appearance: str = ""
    outfit: str = ""
    personality: str = ""
    distinguishing_features: list[str] = Field(default_factory=list)
    palette: list[str] = Field(default_factory=list)
    signature_props: list[str] = Field(default_factory=list)
    reference_images: list[str] = Field(default_factory=list)  # storage-relative
    reference_urls: list[str] = Field(default_factory=list)  # /static/...
    canonical_image: Optional[str] = None  # storage-relative character card
    canonical_url: Optional[str] = None
    embedding_id: Optional[str] = None
    embedding_backend: Optional[str] = None
    appearance_count: int = 0


class Panel(_Base):
    panel_id: str
    index: int
    scene_id: str = ""
    scene_summary: str = ""
    scene_setting: str = ""
    characters: list[str] = Field(default_factory=list)
    action: str = ""
    emotion: Emotion = "neutral"
    intensity: float = 0.5
    expression: str = ""
    emotion_overridden: bool = False
    expression_overridden: bool = False
    dialogue: list[DialogueLine] = Field(default_factory=list)
    narration: Optional[str] = None
    sfx: Optional[str] = None
    camera: Optional[CameraSpec] = None
    visual_prompt: str = ""
    negative_prompt: str = ""
    visual_prompt_overridden: bool = False
    style: StyleName = "manga"
    seed: Optional[int] = None
    image_path: Optional[str] = None  # storage-relative
    image_url: Optional[str] = None  # /static/...
    image_provider: Optional[str] = None
    continuity_score: Optional[float] = None
    continuity_detail: dict[str, Any] = Field(default_factory=dict)
    continuity_passed: Optional[bool] = None
    regenerations: int = 0
    is_edited: bool = False

    @property
    def first_line(self) -> str:
        return self.dialogue[0].text if self.dialogue else ""


class PanelCell(_Base):
    """Placement inside a page grid. Column/row indices are 1-based."""

    panel_id: str
    col_start: int
    col_span: int
    row_start: int
    row_span: int


class PageLayout(_Base):
    page_id: str
    index: int
    template: LayoutTemplate = "grid_2x2"
    template_fallback: bool = False
    template_note: str = ""
    cols: int = 12
    rows: int = 2
    cells: list[PanelCell] = Field(default_factory=list)
    panel_ids: list[str] = Field(default_factory=list)
    image_path: Optional[str] = None
    image_url: Optional[str] = None
    width: int = 1200
    height: int = 1800


class ContinuityReport(_Base):
    threshold: float = 0.62
    mean_score: float = 0.0
    min_score: float = 0.0
    passed: bool = True
    rounds: int = 0
    per_panel: dict[str, float] = Field(default_factory=dict)
    regenerated: list[str] = Field(default_factory=list)


class ExportResult(_Base):
    pdf: Optional[str] = None
    png_zip: Optional[str] = None
    web: Optional[str] = None
    epub: Optional[str] = None
    generated_at: Optional[datetime] = None

    def as_dict(self) -> dict[str, str]:
        return {
            k: v
            for k, v in self.model_dump().items()
            if k != "generated_at" and isinstance(v, str)
        }


class ComicProject(_Base):
    project_id: str
    title: str
    style: StyleName = "manga"
    status: ProjectStatus = "draft"
    story_text: str = ""
    language: str = "en"
    panel_count: int = 0
    panels_per_page: int = 4
    seed: int = 42
    continuity_threshold: float = 0.62

    characters: list[CharacterSheet] = Field(default_factory=list)
    scenes: list[ScenePlan] = Field(default_factory=list)
    panels: list[Panel] = Field(default_factory=list)
    pages: list[PageLayout] = Field(default_factory=list)

    story_analysis: Optional[StoryAnalysis] = None
    continuity: Optional[ContinuityReport] = None
    exports: ExportResult = Field(default_factory=ExportResult)

    error: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def panel_map(self) -> dict[str, Panel]:
        return {p.panel_id: p for p in self.panels}


class CharacterMemoryRecord(_Base):
    character_id: str
    project_id: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    document: str = ""


class ProjectSummary(_Base):
    project_id: str
    title: str
    style: StyleName
    status: ProjectStatus
    panel_count: int
    page_count: int
    character_count: int
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(_Base):
    projects: list[ProjectSummary] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Jobs / progress
# --------------------------------------------------------------------------- #


class JobEvent(_Base):
    seq: int
    ts: datetime = Field(default_factory=_utcnow)
    node: Optional[str] = None
    level: Literal["info", "success", "warning", "error"] = "info"
    message: str = ""
    progress: float = 0.0
    data: dict[str, Any] = Field(default_factory=dict)


class JobSnapshot(_Base):
    job_id: str
    project_id: Optional[str] = None
    status: JobStatusName = "queued"
    current_node: Optional[str] = None
    completed_nodes: list[str] = Field(default_factory=list)
    total_nodes: int = 0
    progress: float = 0.0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    events: list[JobEvent] = Field(default_factory=list)


class NodeInfo(_Base):
    name: str
    label: str
    description: str
    index: int


class PipelineNodesResponse(_Base):
    nodes: list[NodeInfo] = Field(default_factory=list)
    total: int = 0


class ProviderInfo(_Base):
    llm: str
    image: str
    stt: str
    embedding: str
    vector_store: str
    llm_fallback: bool = False
    image_fallback: bool = False
    stt_fallback: bool = False


class HealthResponse(_Base):
    status: str = "ok"
    app: str
    version: str
    environment: str
    mock_mode: bool
    providers: ProviderInfo


class StylePreset(_Base):
    id: str
    name: str
    description: str
    prompt_fragment: str
    negative_fragment: str
    palette: list[str] = Field(default_factory=list)
    bubble_style: str = "rounded"
    font_family: str = "sans"
    line_weight: str = "medium"
    best_for: list[str] = Field(default_factory=list)


class StyleListResponse(_Base):
    styles: list[StylePreset] = Field(default_factory=list)


class DemoStoryResponse(_Base):
    title: str
    story_text: str
    style: StyleName
    panel_count: int
    panels_per_page: int
    characters: list[CharacterRef] = Field(default_factory=list)


PanelUpdateRequest.model_rebuild()
