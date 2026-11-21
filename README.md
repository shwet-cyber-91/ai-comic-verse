# AI ComicVerse

Turn a story into a comic — and keep the characters looking like themselves in
every panel.

You give it a story (typed, pasted, or dictated) and optional character
descriptions/reference images. The pipeline writes the script, designs the
shots, renders each panel from its prompt, then **scores every panel against
available references** and regenerates the ones that drifted. Pollinations uses
the written descriptions rather than directly conditioning on uploaded images.
Out comes a laid-out book as PDF, PNG zip, self-contained web comic, and EPUB.

By default, story analysis uses Gemini 2.5 Flash and panel art uses Pollinations.
Add `GEMINI_API_KEY` to `backend/.env` for Gemini. Pollinations does not require
an API key, and a failed image request is reported instead of being replaced
with mock/Pillow artwork. Pollinations free-tier image requests are serialized
with a 45-second per-IP interval; a 402 rate-limit response gets one retry after
the cooldown. Generating a multi-panel comic can therefore take several minutes.

---

## Provider behavior

Mock providers remain available for offline tests and can be selected explicitly
with `LLM_PROVIDER=mock` or `IMAGE_PROVIDER=mock`. They are not selected as a
fallback for Pollinations image-generation failures.

Gemini requires a valid API key for real story analysis. If it is unavailable,
the backend reports that text-only fallback in the UI. Pollinations errors fail
the image-generation job explicitly; no placeholder artwork is emitted.

---

## Folder tree

```
ai-comicverse/
├── docker-compose.yml           postgres + chroma + backend + frontend
├── README.md
├── scripts/
│   ├── run_local.ps1            one-shot launcher (Windows)
│   └── run_local.sh             one-shot launcher (Linux/macOS/Git Bash)
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt         pinned core (no torch/chroma/opencv)
│   ├── requirements-extras.txt  optional heavy extras, all with fallbacks
│   ├── requirements-dev.txt     pytest
│   ├── pytest.ini
│   ├── .env.example
│   ├── seed/
│   │   └── demo_story.json      the story behind "Load demo story"
│   ├── tests/
│   │   ├── conftest.py          env isolation, fixtures, reference images
│   │   ├── test_nodes.py        node order, JSON retry, full mock run
│   │   ├── test_continuity.py   does the checker actually discriminate?
│   │   ├── test_api.py          every route over HTTP
│   │   └── test_export.py       all four formats
│   └── app/
│       ├── main.py              FastAPI app, /static mount, lifespan
│       ├── config.py            all settings, .env driven
│       ├── schemas.py           the shared contract (Pydantic)
│       ├── state.py             LangGraph TypedDict state
│       ├── graph.py             the pipeline + the panel-repair graph
│       ├── nodes/               14 pipeline nodes, one file each
│       │   ├── base.py          @pipeline_node: events, timing, persistence
│       │   ├── refs.py          reference-image resolution (shared)
│       │   ├── story_input.py … export.py
│       ├── providers/
│       │   ├── base.py          interfaces + the strict-JSON retry contract
│       │   ├── prompts.py       task instructions, schema injection
│       │   ├── llm_mock.py      the text-analysis engine
│       │   ├── llm_gemini.py    Gemini
│       │   ├── llm_ollama.py    Ollama / any local model
│       │   ├── image_mock.py    Pillow renderer (reference-conditioned)
│       │   ├── image_replicate.py  FLUX with reference images
│       │   ├── stt_mock.py, stt_whisper.py
│       │   └── registry.py      selection + graceful fallback
│       ├── continuity/          checker.py — the scorer + the retry budget
│       ├── embeddings/__init__.py   CLIP or a 288-d perceptual fallback
│       ├── memory/              base.py, chroma_store.py, json_store.py
│       ├── styles/presets.py    the six art directions
│       ├── layout_templates.py  12-column grid templates
│       ├── export_engine/       render.py, pdf.py, png_zip.py, web.py, epub.py
│       ├── render_utils.py      fonts, bubbles, halftone, tinting
│       ├── storage.py, db.py, jobs.py, logging_config.py, pipeline_meta.py
│       └── api/routes.py        every /api route
│
└── frontend/
    ├── Dockerfile, nginx.conf, vite.config.js
    ├── tailwind.config.js, postcss.config.js, index.html, .env.example
    └── src/
        ├── main.jsx, App.jsx, api.js, index.css
        ├── components/
        │   ├── ui.jsx               cards, banners, drawer, chips
        │   ├── StylePicker.jsx
        │   ├── CharacterUploader.jsx
        │   ├── ProgressTimeline.jsx SSE-driven 14-stage view
        │   ├── PageView.jsx         CSS-grid page renderer
        │   ├── PanelCard.jsx
        │   └── DialogueBubble.jsx
        └── pages/
            ├── CreatePage.jsx       story, mic, style, references, settings
            ├── ProjectsPage.jsx
            ├── ProgressPage.jsx
            ├── EditorPage.jsx       click a panel: dialogue, scene, regenerate
            └── ExportPage.jsx
```

---

## Architecture

**One graph, fourteen nodes.** `app/graph.py` compiles a LangGraph `StateGraph`:

```
story_input → story_understanding → scene_planning → character_memory
  → emotion_detection → dialogue_generation → camera_director
  → visual_prompt_generation → style_selection → image_generation
  → continuity_check ──low score──▶ image_generation   (bounded retry)
                    └──pass──────▶ layout_generator → editor → export → END
```

The state is plain JSON-able dicts; each node validates into Pydantic at its
boundary and dumps back. That keeps LangGraph's merging trivial and means every
node is independently testable.

**Every node gets the same plumbing for free.** `@pipeline_node(name, label)`
rewrites the function so that it emits live progress events into the job
registry (which is what the SSE screen reads), times itself, records a
before/after log in the state, persists a project snapshot to the database after
each step (so the editor opens mid-run), and wraps any exception in a `NodeError`
carrying the node name.

**LLM output is contract-checked, not hoped for.** `BaseLLM.complete_json()`
builds a prompt from the task name *and the Pydantic JSON schema*, calls the
provider, extracts JSON from whatever came back (code fences, prose preamble and
all), validates it, and on failure **retries exactly once** with a repair
instruction before raising `ProviderError`. Adding a node needs no provider
changes — the schema is the interface.

**Continuity is measured, not asserted.** Each panel is embedded (CLIP when
available, otherwise a 288-d perceptual descriptor: 16×16 luma + 32-bin hue) and
compared by cosine to the best matching reference; that is combined
(weight `CONTINUITY_CLIP_WEIGHT`, default 0.65) with the Pearson correlation of
the joint colour histogram over the face region (OpenCV Haar cascade when
installed, otherwise a fixed upper-centre crop). Panels below the threshold are
sent back to `image_generation` with a **different seed**, up to
`CONTINUITY_MAX_RETRIES` (2). The retry budget lives in the checker node, which is
what makes the cycle terminate.

**Progress crosses the thread boundary safely.** The graph runs in a worker
thread (PIL and httpx are synchronous) while SSE runs in the event loop. Rather
than bridging asyncio queues across threads, the job registry keeps an
append-only, lock-guarded event list with monotonic sequence numbers, and the SSE
endpoint polls it with a cursor every 250 ms. Simple, and there is nothing to
race.

**Everything is addressable by one relative path.** Artefacts live under
`STORAGE_DIR` and are referenced as `projects/<id>/panels/p001.png`. The database
stores that, the API returns it, and `/static` serves it — so the same string
works in the API response, the editor, and the export.

---

## Quick start

Everything below is verified on **Python 3.10+** (the Docker image pins 3.11).
Node 18+ for the frontend.

### No Docker (fastest)

**1. Backend**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
copy .env.example .env            # Windows   (cp on macOS/Linux)
python -m uvicorn app.main:app --reload
```

→ API on <http://127.0.0.1:8000>, interactive docs on <http://127.0.0.1:8000/docs>.

**2. Frontend** (second terminal)

```bash
cd frontend
npm install
npm run dev
```

→ UI on <http://localhost:5173>. Enter a story and click **Generate comic**.

Or skip both: `powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1`
(Windows) / `bash scripts/run_local.sh` (Linux, macOS, Git Bash).

### Docker

```bash
docker compose up --build
```

→ UI on <http://localhost:5173>, API on <http://localhost:8000>, PostgreSQL on
5432, Chroma on 8001. Add `GEMINI_API_KEY` to the root `.env` file or export it
in the shell for Gemini story analysis. Images use Pollinations by default.

---

## Switching to real models

Open `backend/.env` and set:

**Pollinations panel art** is the default and needs no key:

```env
IMAGE_PROVIDER=pollinations
```

For optional FLUX rendering with reference-image conditioning:

```env
IMAGE_PROVIDER=replicate
REPLICATE_API_TOKEN=r8_...
REPLICATE_MODEL=black-forest-labs/flux-kontext-pro
```

`app/providers/image_replicate.py` sends the panel prompt **plus your reference
images as data URIs**, using a built-in input mapping for Kontext, PuLID,
IP-Adapter and plain FLUX (override it entirely with `REPLICATE_INPUT_TEMPLATE`,
a JSON object containing `{prompt}`, `{image}`, `{seed}` placeholders). Non-Kontext
models automatically get the reference as the first image input. Get a token at
<https://replicate.com/account/api-tokens>.

**Real story understanding and dialogue:**

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

Or run it entirely locally with no key at all:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
```

**Real voice input:** `STT_PROVIDER=faster_whisper` (local, needs
`pip install faster-whisper`) or `STT_PROVIDER=openai` with `OPENAI_API_KEY`.

**Better embeddings and memory** — both optional, both auto-detected:

```bash
pip install -r requirements-extras.txt   # then uncomment what you want inside it
# or individually:
pip install open-clip-torch==2.29.0      # real CLIP for continuity + memory
pip install chromadb==0.5.23             # Chroma instead of the JSON store
pip install opencv-python-headless==4.10.0.84   # Haar face ROI
```

**Is it actually using them?** Ask the API:

```bash
curl http://127.0.0.1:8000/api/health
```

```json
{"mock_mode": false,
 "providers": {"llm": "gemini", "image": "pollinations", "stt": "mock",
               "embedding": "clip", "vector_store": "json",
               "llm_fallback": false, "image_fallback": false, "stt_fallback": false}}
```

The UI shows the configured providers in the header. If Gemini is unavailable,
the UI warns that story analysis is using its text-only fallback. Pollinations
image failures are surfaced and never replaced with mock artwork.

---

## Using it

1. **Create** — type, paste, or dictate the story (🎙 records from the mic;
   transcription goes through the STT provider). Pick one of six styles, add
   optional character descriptions/reference images, set panel count, panels per page, the
   continuity threshold, and which formats to export.
2. **Progress** — the 14 stages, live, over SSE, with a per-node log.
3. **Editor** — the composed page with real CSS-grid geometry. Click any panel to
   edit its dialogue (speech / thought / shout / whisper / narration / caption /
   SFX), narration, SFX, scene, emotion, expression and cast; or regenerate it —
   optionally with an edited prompt. Change panels-per-page or the page template
   from the sidebar. Continuity scores are shown per panel, with the per-reference
   breakdown.
4. **Export** — PDF, PNG zip (composed pages **and** bubble-free panel art, plus
   `project.json`), a single self-contained HTML web comic, and EPUB.

### The six styles

`manga`, `anime`, `manhwa`, `bengali_comic`, `marvel_like`, `dc_like` — each is a
generic art direction (line weight, palette, screentone/halftone, bubble shape,
typography). They are **not** any publisher's characters or trade dress, and the
prompts never name a copyrighted character.

---

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Status, version, **which providers are really in use** |
| GET | `/api/styles` | The six style presets |
| GET | `/api/pipeline/nodes` | The 14 stages, in order, for the progress UI |
| GET | `/api/seed/demo` | The demo story |
| POST | `/api/characters/refs` | multipart `name`, `description`, `files[]` → stored references |
| POST | `/api/transcribe` | multipart `file` → `{text, language, provider, duration}` |
| POST | `/api/projects` | Create from a `StoryRequest` |
| GET | `/api/projects` | List summaries |
| GET | `/api/projects/{id}` | Full `ComicProject` |
| DELETE | `/api/projects/{id}` | Delete |
| POST | `/api/projects/{id}/generate` | Queue a run → `{job_id, status}` |
| GET | `/api/jobs/{job_id}` | Snapshot (`?since=<seq>` for incremental) |
| GET | `/api/jobs/{job_id}/events` | **SSE** stream, ends with `event: end` |
| PATCH | `/api/projects/{id}/panels/{panel_id}` | Edit dialogue / scene / emotion |
| POST | `/api/projects/{id}/panels/{panel_id}/regenerate` | Re-render one panel |
| PATCH | `/api/projects/{id}/layout` | `{template, panels_per_page}` |
| POST | `/api/projects/{id}/export` | `{formats: [...]}` |
| GET | `/api/projects/{id}/download/{fmt}` | Download `pdf` / `png_zip` / `web` / `epub` |

---

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest -q
```

Four suites, all offline and all in MOCK mode (the fixtures redirect
`STORAGE_DIR`/`SQLITE_PATH` to a temp folder before the app is imported, so your
real data is never touched):

- `test_nodes.py` — the node order matches the spec; JSON extraction survives
  fences and prose; a flaky provider is repaired by the single retry and a
  hopeless one raises after the budget; every node's output is schema-valid; the
  editor changes only the fields it was given; the layout covers every panel; a
  full pipeline run produces a complete comic with images on disk; the same seed
  produces identical prompts and dialogue.
- `test_continuity.py` — embeddings are deterministic and unit-normalised; a
  panel built from the reference scores high and passes; an unrelated scene scores
  lower; a strict threshold flips pass to fail; a panel with no reference is
  *skipped* rather than failed (otherwise the retry loop would spin); a missing
  image fails instead of crashing.
- `test_api.py` — health, styles, node list, demo story, reference upload round
  trip (and that the upload is immediately servable through `/static`),
  transcription, the create → generate → poll → edit → regenerate → layout →
  export → download journey, the SSE stream terminating, and 404s.
- `test_export.py` — all four formats are written and non-trivial; the PDF has a
  real header and trailer; the zip contains pages, panel art and metadata; the web
  export has no external requests; the EPUB has a valid `mimetype` and a cover;
  one broken exporter does not block the others.

---

## Known limitations

**Honest list, not a wish list.**

1. **MOCK art is placeholder art.** It composites your real reference images into
   styled panels so continuity scoring is genuinely exercised, but it is not a
   diffusion model. Set `IMAGE_PROVIDER=replicate` for real panels.
2. **Continuity is a similarity check, not identity recognition.** Cosine
   similarity over CLIP (or the perceptual fallback) plus a colour-histogram
   correlation answers "does this panel still look like this character", which is
   what a bounded auto-regeneration loop can act on. It will not catch a swapped
   costume that happens to match in overall tone, and it can be fooled by a very
   different pose at the same palette. Identity embeddings (ArcFace) would be
   stronger; the checker is written so a second scorer can be added to `_combine`.
3. **Without CLIP the fallback descriptor is weak.** Real discrimination needs
   `pip install open-clip-torch` (~2 GB with torch). The fallback is good enough to
   separate a portrait from a landscape, which is what the tests assert — not
   enough to distinguish two similar characters.
4. **Face detection needs OpenCV.** Without it the "face ROI" is a fixed
   upper-centre crop, which is the right region for the mock renderer's framing but
   only approximate for real renders.
5. **The mock LLM is rule-based.** It reads sentence structure, capitalisation,
   dialogue attribution and keyword lexicons. It will not invent a plot twist and
   it can misattribute a line when two characters share a paragraph. Gemini or a
   local Llama fixes this without touching any node.
6. **Character memory is not used to *condition* generation yet.** It is built,
   embedded and searchable (`CharacterMemory.query`), and the canonical card is
   used as an extra continuity reference — but the retrieved records are not yet
   injected into the image prompt. That is the obvious next step.
7. **Emotion detection reads text, not faces.** It is an LLM pass over each beat,
   not a facial-expression classifier, so it cannot react to what a renderer
   actually produced.
8. **Voice input is one-shot.** Record, transcribe, insert. There is no streaming
   partial transcript and no speaker diarisation, so a two-voice recording lands as
   one block of text.
9. **No authentication, no rate limiting, no multi-tenancy.** One `STORAGE_DIR` and
   one database, single-user. Do not expose this directly to the internet.
10. **Jobs live in memory.** A restart loses in-flight job progress (the project
    snapshots written after each node survive, so a finished project is never
    lost). One generation per worker; `_MAX_JOBS = 50` keeps the registry bounded.
11. **The editor is per-panel, not per-bubble.** You can add, remove and re-order
    lines, but bubble placement on the page is automatic.
12. **Layout templates are fixed.** Twelve 12-column grids; "auto_grid" covers any
    count, but you cannot drag a panel to an arbitrary rectangle.
13. **Moderation is not included.** Panel prompts come from your story and your
    style preset, and are passed to the image provider as-is. Whatever content
    policy your provider enforces is the only one in play.
14. **The `langgraph==0.2.60` pin** is the most likely to need a bump on a fresh
    machine (its dependency tree moves). The graph only uses `StateGraph`,
    `START`, `END` and `add_conditional_edges`, so `langgraph>=0.2.60,<0.7` is
    fine if pip cannot resolve the exact pin.
15. **Docker's `chroma` service is provisioned but not used by default.** The
    backend uses the JSON store with Chroma running alongside it; install
    `chromadb` in the backend image to switch it on (`VECTOR_STORE=chroma`).

---

## Licence and content

Style presets are generic art directions. The pipeline never names a copyrighted
character, and the reference images you upload are yours to supply — the system
conditions on them, it does not fetch anything.
