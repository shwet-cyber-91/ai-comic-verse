"""Mock image provider.

Renders a panel with PIL. This is the provider that makes the no-key demo
meaningful rather than decorative: when a character has a reference image, that
actual image is composited into the panel (fitted, masked, and pushed through the
same style filter as the rest of the frame). The continuity checker therefore
compares the panel against a genuine rendering of the reference, so scores and
regeneration retries reflect real behaviour instead of being trivially zero.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from ..config import get_settings
from ..logging_config import get_logger
from ..render_utils import (
    fit_cover,
    get_font,
    hex_to_rgb,
    palette_gradient,
    paste_rgba,
    placeholder_portrait,
    style_filter,
    text_size,
    vignette,
    wrap_text,
)
from ..styles.presets import get_style_preset
from .base import ImageProvider, ImageRequest, ImageResult

log = get_logger("providers.image.mock")

SCENE_TYPES = {
    "interior": ["room", "bedroom", "home", "house", "kitchen", "apartment", "corridor", "office"],
    "city": ["street", "city", "road", "alley", "traffic", "market", "bazaar", "town", "square", "roof"],
    "forest": ["forest", "tree", "woods", "jungle", "grove", "park", "field"],
    "space": ["space", "starship", "orbit", "cockpit", "station", "mars", "colony", "airlock"],
    "water": ["river", "shore", "bank", "bridge", "sea", "lake", "harbour", "harbor"],
}

TIME_TINTS = {
    "dawn": ((255, 200, 150), 0.18),
    "day": ((255, 255, 255), 0.0),
    "dusk": ((255, 150, 90), 0.20),
    "night": ((40, 55, 120), 0.32),
}


class MockImageProvider(ImageProvider):
    name = "mock"

    @property
    def supports_reference_images(self) -> bool:
        return True

    # -- entry point -------------------------------------------------------
    def generate(self, request: ImageRequest) -> ImageResult:
        settings = get_settings()
        size = max(256, min(1536, request.size or settings.image_size))
        rng = random.Random(request.seed or settings.seed)

        canvas = palette_gradient(request.style, (size, size), shift=rng.random())
        self._draw_environment(canvas, request, rng)

        names = list(request.character_names) or ["protagonist"]
        refs = list(request.reference_images)
        boxes = self._placements(len(names), request.shot, size)

        for index, name in enumerate(names):
            box = boxes[index % len(boxes)]
            ref = refs[index] if index < len(refs) else (refs[0] if refs else None)
            self._draw_character(canvas, box, name, ref, request, index)

        self._draw_caption(canvas, request)

        styled = style_filter(canvas, request.style)
        tint_colour, tint_strength = TIME_TINTS.get(
            (request.time_of_day or "day").lower(), ((255, 255, 255), 0.0)
        )
        if tint_strength:
            overlay = Image.new("RGB", styled.size, tint_colour)
            styled = Image.blend(styled, overlay, tint_strength)
        styled = vignette(styled, strength=0.28)
        self._draw_frame(styled, request)

        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        styled.save(output, format="PNG", optimize=True)

        log.debug("mock panel %s -> %s (%dx%d)", request.panel_id, output.name, size, size)
        return ImageResult(
            path=str(output),
            provider=self.name,
            seed=request.seed,
            meta={
                "size": size,
                "style": request.style,
                "shot": request.shot,
                "characters": names,
                "used_reference": bool(refs),
            },
        )

    # -- scene -------------------------------------------------------------
    def _scene_type(self, request: ImageRequest) -> str:
        # time of day is packed into the setting string by the prompt builder
        haystack = f"{request.setting} {request.action}".lower()
        for scene_type, words in SCENE_TYPES.items():
            if any(word in haystack for word in words):
                return scene_type
        return "generic"

    def _draw_environment(self, canvas: Image.Image, request: ImageRequest, rng: random.Random) -> None:
        draw = ImageDraw.Draw(canvas, "RGBA")
        width, height = canvas.size
        scene = self._scene_type(request)
        horizon = int(height * 0.62)
        ink = (18, 18, 22, 235)
        mid = (60, 60, 70, 160)

        if scene == "space":
            for _ in range(140):
                x, y = rng.randrange(width), rng.randrange(int(height * 0.7))
                r = rng.choice([1, 1, 2])
                draw.ellipse((x, y, x + r, y + r), fill=(255, 255, 255, 200))
            pr = int(width * 0.16)
            px, py = int(width * 0.76), int(height * 0.2)
            draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=(120, 90, 160, 180), outline=ink, width=3)
            draw.line((0, horizon + 40, width, horizon + 40), fill=ink, width=4)
            return

        if scene == "city":
            x = -20
            while x < width:
                w = rng.randint(50, 130)
                h = rng.randint(int(height * 0.12), int(height * 0.42))
                top = horizon - h
                draw.rectangle((x, top, x + w, horizon + 30), fill=(45, 45, 55, 220), outline=ink, width=3)
                for wy in range(top + 14, horizon - 10, 26):
                    for wx in range(x + 12, x + w - 12, 24):
                        if rng.random() < 0.55:
                            draw.rectangle((wx, wy, wx + 11, wy + 14), fill=(250, 220, 130, 200))
                x += w + rng.randint(6, 18)
            draw.line((0, horizon + 30, width, horizon + 30), fill=ink, width=5)
            return

        if scene == "forest":
            for _ in range(9):
                tx = rng.randrange(0, width)
                tw = rng.randint(24, 46)
                th = rng.randint(int(height * 0.25), int(height * 0.5))
                draw.rectangle((tx, horizon - th, tx + tw, horizon + 30), fill=(50, 40, 35, 230), outline=ink, width=3)
                draw.polygon(
                    [
                        (tx + tw // 2, horizon - th - rng.randint(40, 90)),
                        (tx - 18, horizon - th + 20),
                        (tx + tw + 18, horizon - th + 20),
                    ],
                    fill=(35, 70, 45, 220),
                    outline=ink,
                )
            draw.line((0, horizon + 30, width, horizon + 30), fill=ink, width=5)
            return

        if scene == "water":
            draw.line((0, horizon, width, horizon), fill=ink, width=5)
            for i in range(9):
                y = horizon + 20 + i * int(height * 0.035)
                draw.line((0, y, width, y), fill=(200, 210, 230, 90), width=2)
            return

        if scene == "interior":
            draw.line((0, horizon + 60, width, horizon + 60), fill=ink, width=5)
            draw.rectangle((int(width * 0.08), int(height * 0.22), int(width * 0.30), horizon + 55), outline=ink, width=4)
            draw.line((int(width * 0.19), int(height * 0.22), int(width * 0.19), horizon + 55), fill=ink, width=3)
            for i in range(4):
                y = int(height * 0.30 + i * 40)
                draw.line((int(width * 0.66), y, int(width * 0.92), y), fill=mid, width=3)
            draw.rectangle((int(width * 0.64), int(height * 0.24), int(width * 0.94), int(height * 0.52)), outline=ink, width=4)
            return

        # generic outdoor
        draw.line((0, horizon, width, horizon), fill=ink, width=5)
        for i in range(3):
            cx = int(width * (0.2 + 0.3 * i))
            draw.polygon(
                [
                    (cx, horizon - rng.randint(60, 140)),
                    (cx - rng.randint(90, 150), horizon),
                    (cx + rng.randint(90, 150), horizon),
                ],
                fill=(55, 75, 60, 160),
                outline=ink,
            )

    # -- characters --------------------------------------------------------
    def _placements(self, count: int, shot: str, size: int) -> list[tuple[int, int, int, int]]:
        """Return pixel boxes (x, y, w, h) for ``count`` characters."""
        count = max(1, count)

        if shot in ("close_up", "extreme_close_up"):
            scale = 1.05 if shot == "close_up" else 1.5
            w = int(size * 0.62 * scale)
            h = int(size * 0.78 * scale)
            return [((size - w) // 2, int(size * 0.08), w, h)] * count

        if shot == "over_the_shoulder" and count >= 2:
            w, h = int(size * 0.52), int(size * 0.72)
            return [
                (-int(w * 0.25), int(size * 0.30), w, h),
                (int(size * 0.44), int(size * 0.16), int(w * 0.78), int(h * 0.85)),
            ] + [((size - w) // 2, int(size * 0.22), w, h)] * (count - 2)

        if shot in ("establishing_wide", "wide", "bird_eye"):
            w = int(size * (0.30 if shot == "wide" else 0.22))
            h = int(w * 1.35)
            gap = (size - w * count) / (count + 1)
            y = int(size * 0.30) if shot == "bird_eye" else int(size * 0.44)
            return [
                (int(gap + i * (w + gap)), y + (i % 2) * int(size * 0.03), w, h)
                for i in range(count)
            ]

        if shot in ("low_angle", "high_angle"):
            w, h = int(size * 0.40), int(size * 0.60)
            y = int(size * 0.34) if shot == "low_angle" else int(size * 0.30)
            gap = (size - w * count) / (count + 1)
            return [(int(gap + i * (w + gap)), y, w, h) for i in range(count)]

        w, h = int(size * 0.44), int(size * 0.62)
        gap = (size - w * count) / (count + 1)
        y = int(size * 0.24)
        return [(int(gap + i * (w + gap)), y + (i % 2) * 14, w, h) for i in range(count)]

    def _draw_character(
        self,
        canvas: Image.Image,
        box: tuple[int, int, int, int],
        name: str,
        ref_path: str | None,
        request: ImageRequest,
        index: int,
    ) -> None:
        x, y, w, h = box
        close_up = request.shot in ("close_up", "extreme_close_up")

        figure: Image.Image | None = None
        if ref_path and Path(ref_path).exists():
            try:
                source = Image.open(ref_path).convert("RGB")
                centering = (0.5, 0.28) if close_up else (0.5, 0.42)
                figure = fit_cover(source, (w, h), centering=centering)
            except Exception as exc:  # unreadable reference should not kill the panel
                log.warning("could not read reference %s: %s", ref_path, exc)
                figure = None

        if figure is None:
            colour = hex_to_rgb(request.character_colors.get(name, "#6b7fa8"))
            figure = placeholder_portrait((w, h), colour, emotion=request.emotion, name=name)
        else:
            # soft elliptical mask so the pasted photo reads as a drawn figure
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, w - 1, h - 1), fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(max(3, w // 40)))
            canvas.paste(figure, (x, y), mask)
            outline = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(outline).ellipse((0, 0, w - 1, h - 1), outline=(15, 15, 20, 255), width=max(3, w // 90))
            paste_rgba(canvas, outline, (x, y))
            if not close_up:
                self._draw_name_tag(canvas, (x + w // 2, y - 6), name)
            return

        paste_rgba(canvas, figure, (x, y))
        if not close_up:
            self._draw_name_tag(canvas, (x + w // 2, y - 6), name)

    def _draw_name_tag(self, canvas: Image.Image, anchor: tuple[int, int], name: str) -> None:
        draw = ImageDraw.Draw(canvas, "RGBA")
        font = get_font(max(12, canvas.size[0] // 48), bold=True)
        width, height = text_size(draw, name, font)
        cx, y = anchor
        x = max(4, min(canvas.size[0] - width - 8, cx - width // 2))
        y = max(4, y)
        draw.rectangle((x - 6, y - 4, x + width + 6, y + height + 8), fill=(0, 0, 0, 150))
        draw.text((x, y), name, font=font, fill=(255, 255, 255, 255))

    # -- chrome ------------------------------------------------------------
    def _draw_caption(self, canvas: Image.Image, request: ImageRequest) -> None:
        text = (request.action or "").strip()
        draw = ImageDraw.Draw(canvas, "RGBA")
        width, height = canvas.size
        bar_h = max(30, height // 22)
        draw.rectangle((0, height - bar_h, width, height), fill=(0, 0, 0, 130))
        font_size = max(11, height // 46)
        font = get_font(font_size)
        lines = wrap_text(draw, text, font, width - 24)[:1]
        caption = f"P{request.panel_id}  {lines[0] if lines else ''}".strip()
        draw.text((10, height - bar_h + (bar_h - font_size) // 2), caption, font=font, fill=(240, 240, 240, 255))

    def _draw_frame(self, canvas: Image.Image, request: ImageRequest) -> None:
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size
        ink = (12, 12, 15)
        for i in range(4):
            draw.rectangle((i, i, width - 1 - i, height - 1 - i), outline=ink)
        # corner swatch in the style's accent colour, so styles are distinguishable at a glance
        palette = get_style_preset(request.style).palette
        accent = hex_to_rgb(palette[2] if len(palette) > 2 else "#ffffff")
        draw.rectangle((width - 26, 8, width - 8, 26), fill=accent)


def build_mock_image_provider() -> MockImageProvider:
    return MockImageProvider()
