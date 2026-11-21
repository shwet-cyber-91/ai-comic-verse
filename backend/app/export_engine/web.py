"""Web comic export: one self-contained HTML file.

Images are embedded as base64 so the file works when it is opened from disk,
emailed, or dropped on any static host - no sibling asset folder to lose.
"""

from __future__ import annotations

import base64
from html import escape
from io import BytesIO
from pathlib import Path

from ..logging_config import get_logger
from ..styles.presets import get_style_preset
from .render import compose_all_pages

log = get_logger("export.web")

WEB_MAX_WIDTH = 900
WEB_QUALITY = 86


def _encode_page(image) -> str:
    from PIL import Image

    ratio = WEB_MAX_WIDTH / float(image.width)
    resized = image.resize((WEB_MAX_WIDTH, int(image.height * ratio)), Image.LANCZOS)
    buffer = BytesIO()
    resized.save(buffer, format="JPEG", quality=WEB_QUALITY, optimize=True, progressive=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --ink: #14141a;
    --paper: {paper};
    --accent: {accent};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: radial-gradient(circle at 50% 0%, #22222c 0%, #101014 70%);
    color: #f2f2f5;
    font-family: ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif;
    min-height: 100vh;
  }}
  header {{
    max-width: {width}px;
    margin: 0 auto;
    padding: 34px 18px 10px;
  }}
  h1 {{ margin: 0 0 6px; font-size: clamp(22px, 4vw, 36px); letter-spacing: -0.02em; }}
  .meta {{ color: #9d9dad; font-size: 14px; display: flex; gap: 14px; flex-wrap: wrap; }}
  .meta span {{ border: 1px solid #33333f; border-radius: 999px; padding: 3px 11px; }}
  main {{
    max-width: {width}px;
    margin: 0 auto;
    padding: 18px 18px 60px;
    display: flex;
    flex-direction: column;
    gap: 22px;
  }}
  figure {{
    margin: 0;
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 18px 48px rgba(0,0,0,.55);
    border: 1px solid #2c2c36;
    background: var(--paper);
  }}
  figure img {{ display: block; width: 100%; height: auto; }}
  figcaption {{
    padding: 9px 14px;
    font-size: 13px;
    color: #8f8f9e;
    display: flex;
    justify-content: space-between;
  }}
  footer {{
    text-align: center;
    color: #6c6c7a;
    font-size: 12px;
    padding-bottom: 40px;
  }}
  @media print {{
    body {{ background: #fff; color: #000; }}
    header, footer, figcaption {{ display: none; }}
    main {{ gap: 0; padding: 0; max-width: none; }}
    figure {{ border: 0; border-radius: 0; box-shadow: none; page-break-after: always; }}
  }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta">
    <span>{style}</span>
    <span>{panel_count} panels</span>
    <span>{page_count} pages</span>
    <span>{cast}</span>
  </div>
</header>
<main>
{pages}
</main>
<footer>Generated with AI ComicVerse · use ← and → to move between pages</footer>
<script>
  const figures = Array.from(document.querySelectorAll('figure'));
  let current = 0;
  function go(delta) {{
    current = Math.max(0, Math.min(figures.length - 1, current + delta));
    figures[current].scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  }}
  document.addEventListener('keydown', (event) => {{
    if (event.key === 'ArrowRight' || event.key === 'PageDown') go(1);
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') go(-1);
  }});
</script>
</body>
</html>
"""


def export_web(project, output_path: Path) -> Path:
    images = compose_all_pages(project)
    if not images:
        raise ValueError("nothing to export: the project has no pages")

    preset = get_style_preset(project.style)
    palette = preset.palette or ["#141418"]

    figures = []
    for index, image in enumerate(images, start=1):
        encoded = _encode_page(image)
        figures.append(
            f'  <figure id="page-{index}">\n'
            f'    <img src="data:image/jpeg;base64,{encoded}" alt="Page {index}" loading="lazy">\n'
            f'    <figcaption><span>Page {index}</span><span>{len(project.pages[index - 1].cells)} panels</span></figcaption>\n'
            f"  </figure>"
        )

    cast = ", ".join(c.name for c in project.characters) or "no named cast"
    html = PAGE_TEMPLATE.format(
        title=escape(project.title),
        style=escape(preset.name),
        panel_count=len(project.panels),
        page_count=len(project.pages),
        cast=escape(cast),
        pages="\n".join(figures),
        width=WEB_MAX_WIDTH,
        paper=escape(palette[-1] if palette else "#ffffff"),
        accent=escape(palette[2] if len(palette) > 2 else "#f2b23e"),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    log.info("web comic written: %s (%d page(s))", output_path.name, len(images))
    return output_path
