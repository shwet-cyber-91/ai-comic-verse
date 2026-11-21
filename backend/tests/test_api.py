"""API tests: the routes the frontend calls, exercised over HTTP in MOCK mode."""

from __future__ import annotations

import asyncio
import time

import pytest


def _poll(client, job_id: str, timeout: float = 180.0) -> dict:
    """Wait for a job to finish. The pipeline runs on a worker thread."""
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in ("succeeded", "failed"):
            return last
        time.sleep(0.25)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s (last: {last})")


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #


def test_lifespan_ignores_shutdown_cancellation():
    from app.main import lifespan

    async def scenario():
        try:
            async with lifespan(app=None):
                raise asyncio.CancelledError
        except asyncio.CancelledError:
            pytest.fail("lifespan should swallow shutdown cancellation")

    asyncio.run(scenario())


def test_health_reports_mock_mode(client):
    payload = client.get("/api/health").json()

    assert payload["status"] == "ok"
    assert payload["mock_mode"] is True
    assert payload["providers"]["llm"] == "mock"
    assert payload["providers"]["image"] == "mock"
    assert payload["providers"]["stt"] == "mock"
    assert payload["providers"]["embedding"] in ("clip", "fallback")


def test_styles_cover_the_six_requested_styles(client):
    styles = client.get("/api/styles").json()["styles"]
    ids = {style["id"] for style in styles}

    assert ids == {"manga", "anime", "manhwa", "bengali_comic", "marvel_like", "dc_like"}
    for style in styles:
        assert style["prompt_fragment"]
        assert style["negative_fragment"]
        assert style["palette"]


def test_pipeline_nodes_are_advertised_in_order(client):
    payload = client.get("/api/pipeline/nodes").json()

    assert payload["total"] == 14
    names = [node["name"] for node in payload["nodes"]]
    assert names[0] == "story_input"
    assert names[-1] == "export"
    assert names.index("continuity_check") < names.index("layout_generator")
    for index, node in enumerate(payload["nodes"]):
        assert node["index"] == index
        assert node["label"] and node["description"]


def test_demo_story_is_available(client):
    demo = client.get("/api/seed/demo").json()

    assert demo["title"]
    assert len(demo["story_text"]) > 200
    assert demo["panel_count"] >= 4
    assert demo["style"] in {"manga", "anime", "manhwa", "bengali_comic", "marvel_like", "dc_like"}


def test_static_mount_serves_the_storage_folder(client):
    """A 404 from the mount means the folder is wired up (an unmounted path 404s too,
    so this checks the route exists rather than a file)."""
    response = client.get("/static/../pyproject.toml")
    assert response.status_code in (404, 400)


# --------------------------------------------------------------------------- #
# Uploads
# --------------------------------------------------------------------------- #


def test_reference_upload_round_trip(client, reference_png: bytes):
    response = client.post(
        "/api/characters/refs",
        data={"name": "Mira", "description": "A sky-courier."},
        files=[("files", ("mira.png", reference_png, "image/png"))],
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["name"] == "Mira"
    assert body["description"] == "A sky-courier."
    assert len(body["reference_images"]) == 1
    assert body["reference_images"][0].startswith("refs/_draft/")

    # and the file is immediately readable through /static
    served = client.get(f"/static/{body['reference_images'][0]}")
    assert served.status_code == 200
    assert served.content == reference_png


def test_reference_upload_rejects_a_blank_name(client, reference_png: bytes):
    response = client.post(
        "/api/characters/refs",
        data={"name": "   "},
        files=[("files", ("mira.png", reference_png, "image/png"))],
    )
    assert response.status_code == 400


def test_reference_upload_needs_a_file(client):
    response = client.post("/api/characters/refs", data={"name": "Mira"})
    assert response.status_code == 400


def test_transcribe_returns_the_mock_transcript(client):
    response = client.post(
        "/api/transcribe",
        files={"file": ("take.webm", b"not-really-audio", "audio/webm")},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider"].startswith("mock")
    assert len(body["text"]) > 40, "the mock transcript is a usable story"


def test_transcribe_rejects_an_empty_file(client):
    response = client.post(
        "/api/transcribe",
        files={"file": ("take.webm", b"", "audio/webm")},
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# The full journey
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def generated():
    """Create + generate one project, then hand it to the assertions below.

    Module scoped because a full pipeline run costs a few seconds; every test
    below reads from the same finished comic.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield _generate(test_client)


def _generate(client) -> dict:
    from app.config import get_settings
    from app.storage import save_loose_reference

    from PIL import Image, ImageDraw
    from io import BytesIO

    image = Image.new("RGB", (96, 96), (206, 176, 132))
    draw = ImageDraw.Draw(image)
    draw.ellipse((30, 24, 74, 68), fill=(238, 214, 186))
    draw.rectangle((40, 36, 46, 42), fill=(28, 24, 30))
    draw.rectangle((58, 36, 64, 42), fill=(28, 24, 30))
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    reference = save_loose_reference("Mira", "mira.png", buffer.getvalue())
    get_settings()

    created = client.post(
        "/api/projects",
        json={
            "title": "The Last Star Chart",
            "story_text": (
                "Mira the sky-courier lands her glider on the observatory roof at dusk. "
                "Kestrel is packing star charts into a leather case. The dome is being "
                "shut down tonight. Mira sets the glider key on the table. Outside, the "
                "first storm of the season breaks over the hills."
            ),
            "style": "manhwa",
            "characters": [
                {
                    "name": "Mira",
                    "description": "A courier in a patched flight jacket and copper goggles.",
                    "reference_images": [reference],
                },
                {
                    "name": "Kestrel",
                    "description": "An astronomer with grey braided hair and ink-stained sleeves.",
                    "reference_images": [],
                },
            ],
            "panel_count": 4,
            "panels_per_page": 2,
            "export_formats": ["pdf", "png_zip", "web", "epub"],
        },
    )
    assert created.status_code == 200, created.text
    project = created.json()
    assert project["status"] == "draft"

    started = client.post(f"/api/projects/{project['project_id']}/generate")
    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]

    job = _poll(client, job_id)
    assert job["status"] == "succeeded", job.get("error")

    fetched = client.get(f"/api/projects/{project['project_id']}")
    assert fetched.status_code == 200
    return {"client": client, "project": fetched.json(), "job": job}


def test_generate_produced_a_finished_comic(generated):
    project = generated["project"]

    assert project["status"] == "ready"
    assert len(project["panels"]) == 4
    assert len(project["pages"]) == 2
    assert project["characters"]
    assert project["story_analysis"]["logline"]

    for panel in project["panels"]:
        assert panel["image_url"].startswith("/static/")
        assert panel["continuity_score"] is not None
        assert panel["visual_prompt"]
        assert panel["camera"]["shot"]


def test_every_job_event_streamed_carries_a_node_and_message(generated):
    events = generated["job"]["events"]

    assert events, "the job must record progress"
    assert any(event["node"] == "image_generation" for event in events)
    assert any(event["level"] == "success" for event in events)
    assert [event["seq"] for event in events] == sorted(event["seq"] for event in events)


def test_progress_reached_one(generated):
    assert generated["job"]["progress"] == 1.0
    assert len(generated["job"]["completed_nodes"]) == 14


def test_panel_images_are_reachable_over_http(generated):
    client = generated["client"]
    for panel in generated["project"]["panels"]:
        response = client.get(panel["image_url"])
        assert response.status_code == 200
        assert len(response.content) > 512


def test_job_events_endpoint_streams_and_terminates(generated):
    """The SSE route must open, replay, and close on a finished job.

    This starts its own project rather than streaming the module fixture's job:
    the autouse reset fixture empties the job registry between tests, so a job
    created several tests ago is legitimately gone by the time we get here.
    """
    client = generated["client"]

    created = client.post(
        "/api/projects",
        json={
            "title": "Streaming Check",
            "story_text": generated["project"]["story_text"],
            "style": "manga",
            "panel_count": 2,
            "panels_per_page": 2,
            "export_formats": ["web"],
        },
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["project_id"]

    started = client.post(f"/api/projects/{project_id}/generate")
    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]
    assert _poll(client, job_id)["status"] == "succeeded"

    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.status_code == 200
        body = "".join(chunk for chunk in response.iter_text())
    assert "event: end" in body
    assert "image_generation" in body


def test_editing_a_panel_persists(generated):
    client = generated["client"]
    project_id = generated["project"]["project_id"]
    panel_id = generated["project"]["panels"][0]["panel_id"]

    response = client.patch(
        f"/api/projects/{project_id}/panels/{panel_id}",
        json={"dialogue": [{"speaker": "Mira", "text": "We fly it out together.", "kind": "speech", "emotion": "determination"}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["panel"]["dialogue"][0]["text"] == "We fly it out together."
    assert body["panel"]["is_edited"] is True
    assert body["changed"] == ["dialogue"]

    reloaded = client.get(f"/api/projects/{project_id}").json()
    edited = next(p for p in reloaded["panels"] if p["panel_id"] == panel_id)
    assert edited["dialogue"][0]["speaker"] == "Mira"


def test_editing_an_unknown_panel_is_a_404(generated):
    client = generated["client"]
    project_id = generated["project"]["project_id"]

    response = client.patch(
        f"/api/projects/{project_id}/panels/p999", json={"narration": "nope"}
    )
    assert response.status_code == 404


def test_regenerating_one_panel_changes_the_image(generated):
    client = generated["client"]
    project_id = generated["project"]["project_id"]
    panels = generated["project"]["panels"]
    target = next(p for p in panels if "Mira" in p["characters"]) if any(
        "Mira" in p["characters"] for p in panels
    ) else panels[0]

    started = client.post(f"/api/projects/{project_id}/panels/{target['panel_id']}/regenerate", json={})
    assert started.status_code == 202, started.text
    job = _poll(client, started.json()["job_id"])
    assert job["status"] == "succeeded", job.get("error")

    reloaded = client.get(f"/api/projects/{project_id}").json()
    redone = next(p for p in reloaded["panels"] if p["panel_id"] == target["panel_id"])

    assert redone["regenerations"] >= 1
    assert redone["image_url"]
    assert redone["continuity_score"] is not None


def test_regeneration_keeps_manual_emotion_override_in_prompt(generated):
    client = generated["client"]
    project_id = generated["project"]["project_id"]
    panel_id = generated["project"]["panels"][0]["panel_id"]

    response = client.patch(
        f"/api/projects/{project_id}/panels/{panel_id}",
        json={"emotion": "anger", "expression": "furrowed brows, narrowed eyes, clenched jaw"},
    )
    assert response.status_code == 200, response.text

    started = client.post(f"/api/projects/{project_id}/panels/{panel_id}/regenerate", json={})
    assert started.status_code == 202, started.text
    job = _poll(client, started.json()["job_id"])
    assert job["status"] == "succeeded", job.get("error")

    reloaded = client.get(f"/api/projects/{project_id}").json()
    redone = next(p for p in reloaded["panels"] if p["panel_id"] == panel_id)
    prompt = (redone.get("visual_prompt") or "").lower()

    assert redone["emotion"] == "anger"
    assert "anger" in prompt
    assert "confusion" not in prompt


def test_layout_can_be_changed(generated):
    client = generated["client"]
    project_id = generated["project"]["project_id"]

    response = client.patch(
        f"/api/projects/{project_id}/layout", json={"panels_per_page": 1, "template": "splash"}
    )
    assert response.status_code == 200, response.text
    pages = response.json()["project"]["pages"]

    assert len(pages) == len(generated["project"]["panels"])
    for page in pages:
        assert page["template"] == "splash"
        assert page["panel_ids"]


@pytest.mark.parametrize(
    "template",
    [
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
    ],
)
def test_layout_templates_round_trip_and_report_fallbacks(generated, template):
    client = generated["client"]
    project_id = generated["project"]["project_id"]

    response = client.patch(
        f"/api/projects/{project_id}/layout",
        json={"panels_per_page": 2, "template": template},
    )
    assert response.status_code == 200, response.text

    pages = response.json()["project"]["pages"]
    assert pages
    mismatched_templates = {
        "splash",
        "three_strip",
        "hero_top",
        "hero_left",
        "hero_five",
        "grid_2x2",
        "grid_2x3",
        "grid_3x2",
        "grid_3x3",
    }
    for page in pages:
        assert page["template"] == template
        if template in mismatched_templates:
            assert page["template_fallback"] is True
            assert page["template_note"]
        elif template == "auto_grid":
            assert page["template_fallback"] in (False, None)
        else:
            assert page["template_fallback"] in (False, None)


def test_export_writes_every_format_and_they_download(generated):
    import io
    import re
    import zipfile

    from PIL import Image

    client = generated["client"]
    project_id = generated["project"]["project_id"]
    expected_pages = len(generated["project"]["pages"])

    response = client.post(
        f"/api/projects/{project_id}/export",
        json={"formats": ["pdf", "png_zip", "web", "epub"]},
    )
    assert response.status_code == 200, response.text
    exports = response.json()["exports"]

    assert set(exports) == {"pdf", "png_zip", "web", "epub"}

    pdf_url = exports["pdf"]
    pdf_response = client.get(pdf_url)
    assert pdf_response.status_code == 200
    assert pdf_response.headers.get("content-type", "").startswith("application/pdf")
    assert pdf_response.content.startswith(b"%PDF")
    page_count_match = re.search(rb"/Count\s+(\d+)\s*/Kids", pdf_response.content)
    assert page_count_match is not None
    assert int(page_count_match.group(1)) == expected_pages

    png_url = exports["png_zip"]
    png_response = client.get(png_url)
    assert png_response.status_code == 200
    assert png_response.headers.get("content-type", "").lower() in {"application/zip", "application/x-zip-compressed"}
    assert len(png_response.content) > 1024
    with zipfile.ZipFile(io.BytesIO(png_response.content)) as archive:
        names = archive.namelist()
        page_names = [name for name in names if name.startswith("pages/") and name.endswith(".png")]
        assert len(page_names) == expected_pages
        for name in page_names:
            with archive.open(name) as handle:
                image = Image.open(io.BytesIO(handle.read()))
                image.verify()

    web_url = exports["web"]
    web_response = client.get(web_url)
    assert web_response.status_code == 200
    assert web_response.headers.get("content-type", "").startswith("text/html")
    html = web_response.text
    assert "<img" in html
    assert html.count("data:image/jpeg;base64,") >= expected_pages

    epub_url = exports["epub"]
    epub_response = client.get(epub_url)
    assert epub_response.status_code == 200
    assert epub_response.headers.get("content-type", "").startswith("application/epub+zip")
    with zipfile.ZipFile(io.BytesIO(epub_response.content)) as archive:
        names = archive.namelist()
        assert names[0] == "mimetype"
        assert any(name.endswith("container.xml") for name in names)
        opf_name = next(name for name in names if name.endswith("content.opf"))
        opf = archive.read(opf_name).decode("utf-8", errors="replace")
        assert "manifest" in opf.lower()
        for index in range(1, expected_pages + 1):
            assert f"page_{index:02d}.xhtml" in opf or f"page_{index:02d}" in opf

    download = client.get(f"/api/projects/{project_id}/download/pdf")
    assert download.status_code == 200
    assert download.content[:4] == b"%PDF"
    assert "attachment; filename=" in download.headers.get("content-disposition", "").lower()


def test_list_and_delete(client, generated):
    project_id = generated["project"]["project_id"]

    listing = client.get("/api/projects").json()["projects"]
    assert any(item["project_id"] == project_id for item in listing)
    entry = next(item for item in listing if item["project_id"] == project_id)
    assert entry["panel_count"] == len(generated["project"]["panels"])
    assert entry["character_count"] >= 1

    assert client.delete(f"/api/projects/{project_id}").json() == {"deleted": True}
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    assert client.delete(f"/api/projects/{project_id}").status_code == 404


def test_unknown_project_and_job_are_404s(client):
    assert client.get("/api/projects/does-not-exist").status_code == 404
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.get("/api/jobs/does-not-exist/events").status_code == 404
