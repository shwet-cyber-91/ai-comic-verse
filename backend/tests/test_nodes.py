"""Pipeline node tests: the JSON contract, the state hand-off, and a full run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.nodes import NODE_ORDER, NODE_REGISTRY
from app.nodes.base import NodeError
from app.pipeline_meta import NODE_NAMES
from app.providers.base import ProviderError, extract_json
from app.providers.llm_mock import MockLLM
from app.schemas import DialoguePlan, ScenePlanList, StoryAnalysis
from app.state import initial_state

EXPECTED_ORDER = [
    "story_input",
    "story_understanding",
    "scene_planning",
    "character_memory",
    "emotion_detection",
    "dialogue_generation",
    "camera_director",
    "visual_prompt_generation",
    "style_selection",
    "image_generation",
    "continuity_check",
    "layout_generator",
    "editor",
    "export",
]


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #


def test_node_registry_matches_the_specified_order():
    assert NODE_ORDER == EXPECTED_ORDER
    assert NODE_NAMES == EXPECTED_ORDER
    assert len(NODE_REGISTRY) == 14


def test_every_node_is_callable():
    for spec in NODE_REGISTRY:
        assert callable(spec.run)
        assert spec.description


def test_graph_compiles():
    from app.graph import build_graph, route_after_continuity

    assert build_graph() is not None
    assert route_after_continuity({"regenerate_panel_ids": ["p001"]}) == "retry"
    assert route_after_continuity({"regenerate_panel_ids": []}) == "continue"
    assert route_after_continuity({}) == "continue"


# --------------------------------------------------------------------------- #
# JSON discipline
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Here you go:\n{"a": 1}\nHope that helps!',
        '  \n {"a": {"b": 2}}  ',
        '[1, 2, 3]',
    ],
)
def test_extract_json_survives_model_chatter(raw):
    assert extract_json(raw) is not None


def test_extract_json_rejects_garbage():
    with pytest.raises(ProviderError):
        extract_json("I cannot help with that request.")


class FlakyLLM(MockLLM):
    """Returns prose on the first attempt of every task, then valid JSON."""

    name = "flaky"

    def __init__(self, seed: int = 42) -> None:
        super().__init__(seed=seed)
        self.attempts: dict[str, int] = {}

    def _raw_for_task(self, task, payload, system, user):
        self.attempts[task] = self.attempts.get(task, 0) + 1
        if self.attempts[task] == 1:
            # The real provider doesn't have a valid payload to retry with unless it
            # has already started the task. Keep the test double aligned with that
            # contract so the repair path is exercised exactly once.
            self._last_call = (task, payload)
            self._last = {"error": "invalid first attempt"}
            return "Sure! Here's the JSON you wanted:\n(nothing parseable here)"
        return super()._raw_for_task(task, payload, system, user)


class HopelessLLM(MockLLM):
    """Never returns JSON. The retry budget must be exhausted and reported."""

    name = "hopeless"

    def _raw_for_task(self, task, payload, system, user):
        return "still not JSON, sorry"

    def _generate(self, system, user):
        return "also not JSON"


def test_invalid_json_is_repaired_with_one_retry():
    llm = FlakyLLM()
    result = llm.complete_json(
        "story_understanding",
        {"title": "Test", "story_text": "A pilot lands at dusk."},
        StoryAnalysis,
    )
    assert isinstance(result, StoryAnalysis)
    assert llm.attempts["story_understanding"] == 2, "should fail once, then succeed on the repair"


def test_invalid_json_gives_up_after_the_retry_budget():
    llm = HopelessLLM()
    with pytest.raises(ProviderError) as excinfo:
        llm.complete_json("story_understanding", {"story_text": "x"}, StoryAnalysis)
    assert "invalid JSON" in str(excinfo.value)


def test_demo_story_tracks_only_human_characters_and_location():
    demo_path = Path(__file__).resolve().parents[1] / "seed" / "demo_story.json"
    story = json.loads(demo_path.read_text(encoding="utf-8"))

    llm = MockLLM(seed=42)
    analysis = llm.complete_json(
        "story_understanding",
        {
            "title": story["title"],
            "story_text": story["story_text"],
            "panel_count": story["panel_count"],
            "user_characters": [
                {"name": c["name"], "description": c["description"]}
                for c in story["characters"]
            ],
        },
        StoryAnalysis,
    )

    assert {c.name for c in analysis.characters} == {"Rokeya", "Ishaan"}
    assert "Shonar Bagan" in analysis.setting


def test_demo_story_dialogue_has_no_repeated_lines_or_duplicate_narration():
    demo_path = Path(__file__).resolve().parents[1] / "seed" / "demo_story.json"
    story = json.loads(demo_path.read_text(encoding="utf-8"))

    llm = MockLLM(seed=42)
    panels = [
        {
            "panel_id": f"p{index:03d}",
            "action": f"Scene {index} action",
            "characters": ["Rokeya", "Ishaan"],
            "emotion": "neutral",
            "is_first_of_scene": index == 1,
            "silent": False,
        }
        for index in range(1, 5)
    ]
    plan = llm.complete_json(
        "dialogue_generation",
        {"panels": panels, "story_text": story["story_text"]},
        DialoguePlan,
    )

    all_texts = [line.text for panel in plan.panels for line in panel.lines]
    assert len(all_texts) == len(set(line.lower() for line in all_texts))
    for panel in plan.panels:
        if panel.narration:
            assert not any(
                line.text.strip().lower() == panel.narration.strip().lower() for line in panel.lines
            )


def test_mock_llm_answers_every_task_with_schema_valid_json():
    from app.schemas import (
        CameraPlan,
        CharacterSheetPlan,
        DialoguePlan,
        EmotionPlan,
        PromptPlan,
        StoryAnalysis,
    )

    llm = MockLLM(seed=7)
    story_payload = {"title": "The Last Star Chart", "story_text": "Mira lands at dusk. Kestrel waits."}

    analysis = llm.complete_json("story_understanding", story_payload, StoryAnalysis)
    assert analysis.title
    assert analysis.characters, "the mock must find at least one character"

    sheets = llm.complete_json(
        "character_sheet",
        {"story_text": story_payload["story_text"], "characters": [c.model_dump() for c in analysis.characters]},
        CharacterSheetPlan,
    )
    assert sheets.characters

    scenes = llm.complete_json(
        "scene_planning",
        {"story_text": story_payload["story_text"], "panel_count": 4, "scene_count": 3},
        ScenePlanList,
    )
    assert scenes.scenes

    beats = [
        {
            "panel_id": f"p{index:03d}",
            "scene_id": scene.scene_id,
            "action": scene.action,
            "characters": scene.characters,
            "scene_mood": scene.mood,
        }
        for index, scene in enumerate(scenes.scenes, start=1)
    ]
    emotions = llm.complete_json("emotion_detection", {"beats": beats}, EmotionPlan)
    assert emotions.beats

    # dialogue and camera take the enriched panels, exactly as the nodes send them
    panel_payloads = [
        {
            "panel_id": beat["panel_id"],
            "action": beat["action"],
            "characters": beat["characters"],
            "emotion": emotion.emotion,
            "expression": emotion.expression,
            "scene_setting": scenes.scenes[0].setting,
            "index_in_scene": index,
            "is_first_of_scene": index == 0,
            "is_last_of_scene": index == len(beats) - 1,
        }
        for index, (beat, emotion) in enumerate(zip(beats, emotions.beats))
    ]

    dialogue = llm.complete_json("dialogue_generation", {"panels": panel_payloads}, DialoguePlan)
    assert dialogue.panels

    camera = llm.complete_json("camera_director", {"panels": panel_payloads}, CameraPlan)
    assert camera.panels

    prompts = llm.complete_json(
        "visual_prompt_generation",
        {
            "panels": [
                {**panel, "camera": item.camera.model_dump()}
                for panel, item in zip(panel_payloads, camera.panels)
            ],
            "style": "manga",
            "character_sheets": [c.model_dump() for c in sheets.characters],
        },
        PromptPlan,
    )
    assert prompts.panels
    for panel in prompts.panels:
        assert panel.positive


# --------------------------------------------------------------------------- #
# Individual nodes
# --------------------------------------------------------------------------- #


def test_story_input_normalises_the_request(story_request, fresh_app_state):
    from app.nodes import story_input

    state = initial_state("test0001", story_request)
    update = story_input.run(state)

    assert update["project"]["project_id"] == "test0001"
    assert update["project"]["status"] == "running"
    assert update["plan"]["total"] == 14
    # the loose reference gets copied into the project folder
    stored = update["request"]["characters"][0]["reference_images"][0]
    assert stored.startswith("projects/test0001/refs/")


def test_emotion_and_dialogue_nodes_cover_every_panel(story_request, fresh_app_state):
    from app.nodes import (
        camera_director,
        dialogue_generation,
        emotion_detection,
        scene_planning,
        story_input,
        story_understanding,
        visual_prompt,
    )

    state = initial_state("test0002", story_request)
    for node in (story_input, story_understanding, scene_planning):
        state = {**state, **node.run(state)}

    beats = state["panels"]
    assert len(beats) == story_request["panel_count"]

    for node in (emotion_detection, dialogue_generation, camera_director, visual_prompt):
        state = {**state, **node.run(state)}

    panels = state["project"]["panels"]
    assert len(panels) == story_request["panel_count"]
    for panel in panels:
        assert panel["emotion"]
        assert panel["camera"]["shot"]
        assert panel["visual_prompt"]
        assert panel["dialogue"] or panel["narration"], "every panel needs words or a caption"


def test_editor_applies_only_the_fields_it_is_given(story_request, fresh_app_state):
    from app.nodes.editor import apply_panel_update
    from app.schemas import ComicProject, Panel, PanelUpdateRequest

    project = ComicProject(project_id="p1", title="T", panels=[Panel(panel_id="p001", index=1)])
    panel, changed = apply_panel_update(project, "p001", PanelUpdateRequest(dialogue=[]))

    assert changed == ["dialogue"]
    assert panel.dialogue == []
    assert panel.narration is None
    assert panel.is_edited is True

    with pytest.raises(KeyError):
        apply_panel_update(project, "nope", PanelUpdateRequest(dialogue=[]))


def test_layout_generator_paginates_and_covers_every_panel(fresh_app_state):
    from app.layout_templates import TEMPLATES
    from app.nodes.layout_generator import paginate
    from app.schemas import Panel

    panels = [Panel(panel_id=f"p{index:03d}", index=index) for index in range(1, 8)]
    pages = paginate(panels, 3)

    assert len(pages) == 3
    assert sum(len(page.cells) for page in pages) == 7
    for page in pages:
        assert page.template in TEMPLATES
        assert page.cells
        for cell in page.cells:
            assert cell.col_start >= 1 and cell.row_start >= 1
            assert cell.col_start + cell.col_span - 1 <= page.cols


# --------------------------------------------------------------------------- #
# The whole thing
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def generated_project():
    """One full mock-mode run, shared by the assertions below."""
    import os
    import tempfile

    # module scope needs its own reset dance; the autouse fixture is function scoped
    from app.config import get_settings, reset_settings_cache
    from app.continuity import reset_checker
    from app.db import init_db, reset_engine
    from app.embeddings import reset_embedder
    from app.graph import reset_graphs, run_pipeline
    from app.memory import reset_memory_backend
    from app.providers.registry import reset_providers
    from app.schemas import CharacterRef, StoryRequest
    from app.storage import save_loose_reference

    reset_settings_cache()
    reset_engine()
    reset_providers()
    reset_memory_backend()
    reset_embedder()
    reset_checker()
    reset_graphs()
    init_db()
    os.environ["IMAGE_SIZE"] = "192"

    from PIL import Image, ImageDraw
    from io import BytesIO

    image = Image.new("RGB", (96, 96), (198, 168, 128))
    draw = ImageDraw.Draw(image)
    draw.ellipse((26, 20, 70, 64), fill=(236, 212, 184))
    draw.rectangle((36, 32, 42, 38), fill=(24, 20, 26))
    draw.rectangle((54, 32, 60, 38), fill=(24, 20, 26))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    reference = save_loose_reference("Mira", "mira.png", buffer.getvalue())

    request = StoryRequest(
        title="The Last Star Chart",
        story_text=(
            "Mira the sky-courier lands her glider on the observatory roof at dusk. "
            "Kestrel is packing star charts. The dome is being shut down tonight. "
            "Mira puts the key on the table and says they will fly it out together."
        ),
        style="manga",
        characters=[
            CharacterRef(name="Mira", description="A courier in a patched flight jacket.", reference_images=[reference]),
            CharacterRef(name="Kestrel", description="An astronomer with grey braided hair."),
        ],
        panel_count=4,
        panels_per_page=2,
        export_formats=["pdf", "web"],
    ).model_dump(mode="json")

    project = run_pipeline("gen0001", request)
    return project


def test_pipeline_produces_a_complete_comic(generated_project):
    project = generated_project

    assert project.status == "ready"
    assert len(project.panels) == 4
    assert project.story_analysis is not None
    assert project.scenes
    assert project.characters
    assert project.pages, "the layout generator must produce pages"

    for panel in project.panels:
        assert panel.image_path, f"{panel.panel_id} was never rendered"
        assert panel.image_url and panel.image_url.startswith("/static/")
        assert panel.visual_prompt
        assert panel.continuity_score is not None
        assert 0.0 <= panel.continuity_score <= 1.0


def test_pipeline_records_continuity_and_exports(generated_project):
    project = generated_project

    assert project.continuity is not None
    assert project.continuity.threshold > 0
    assert project.continuity.per_panel

    exports = project.exports.as_dict()
    assert "pdf" in exports, "the PDF export must exist in mock mode"
    assert "web" in exports


def test_images_actually_exist_on_disk(generated_project):
    from app.storage import abs_path

    for panel in generated_project.panels:
        path = abs_path(panel.image_path)
        assert path.exists(), f"missing panel image {path}"
        assert path.stat().st_size > 512


def test_pipeline_handles_short_two_character_story_in_mock_mode(fresh_app_state):
    from app.graph import run_pipeline
    from app.schemas import CharacterRef, StoryRequest

    request = StoryRequest(
        title="Luna and Theo",
        story_text=(
            "Luna and Theo meet on the station platform at dawn. Luna's scarf catches in the wind. "
            "Theo reaches out, and together they decide to leave before the train arrives."
        ),
        style="manga",
        characters=[
            CharacterRef(name="Luna", description="A quick-witted courier with a bright scarf."),
            CharacterRef(name="Theo", description="A calm mechanic with a steady hand."),
        ],
        panel_count=4,
        panels_per_page=2,
        export_formats=["web"],
    ).model_dump(mode="json")

    project = run_pipeline("mock-short-story", request)

    assert project.status == "ready"
    assert len(project.panels) == request["panel_count"]
    assert project.story_analysis is not None
    assert {c.name.lower() for c in project.characters} >= {"luna", "theo"}
    assert all(panel.image_path for panel in project.panels)
    assert project.exports.web


def test_pipeline_is_deterministic_for_a_fixed_seed(fresh_app_state, story_request):
    """Same story + same seed => identical prompts and dialogue."""
    from app.graph import run_pipeline

    story_request["seed"] = 99
    story_request["export_formats"] = ["web"]
    first = run_pipeline("det0001", story_request)
    second = run_pipeline("det0002", story_request)

    assert [p.visual_prompt for p in first.panels] == [p.visual_prompt for p in second.panels]
    assert [p.emotion for p in first.panels] == [p.emotion for p in second.panels]
    assert [
        [(line.speaker, line.text) for line in p.dialogue] for p in first.panels
    ] == [[(line.speaker, line.text) for line in p.dialogue] for p in second.panels]
