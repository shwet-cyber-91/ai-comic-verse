"""Shared raster drawing helpers.

Used by both the mock image provider (which renders panels) and the export
engine (which composes panels into pages and bakes speech bubbles), so a panel
looks the same in the editor and in the PDF.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .logging_config import get_logger
from .styles.presets import get_style_preset

log = get_logger("render")

# Candidate system fonts, per family. First one that exists wins.
FONT_CANDIDATES: dict[str, list[str]] = {
    "sans": [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
    "sans_bold": [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
    "serif": [
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/times.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
    ],
    "serif_bold": [
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    ],
}


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = (value or "#000000").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0, 0, 0)


def mix(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))  # type: ignore[return-value]


@lru_cache(maxsize=64)
def get_font(size: int, bold: bool = False, family: str = "sans") -> ImageFont.FreeTypeFont:
    key = f"{family}_{'bold' if bold else 'regular'}"
    candidates = FONT_CANDIDATES.get(key) or FONT_CANDIDATES["sans"]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:  # pragma: no cover
                continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    if not text:
        return (0, 0)
    box = draw.textbbox((0, 0), text, font=font)
    return (box[2] - box[0], box[3] - box[1])


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Greedy word wrap that also hard-breaks words longer than max_width."""
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if text_size(draw, trial, font)[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
        while text_size(draw, current, font)[0] > max_width and len(current) > 1:
            # hard break an over-long single word
            cut = len(current)
            while cut > 1 and text_size(draw, current[:cut], font)[0] > max_width:
                cut -= 1
            lines.append(current[:cut])
            current = current[cut:]
    if current:
        lines.append(current)
    return lines


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int],
    start_size: int,
    min_size: int = 10,
    bold: bool = False,
    family: str = "sans",
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Shrink the font until the wrapped text fits inside ``box`` (w, h)."""
    max_w, max_h = box
    size = start_size
    while size > min_size:
        font = get_font(size, bold=bold, family=family)
        lines = wrap_text(draw, text, font, max_w)
        line_h = int(size * 1.28)
        if lines and line_h * len(lines) <= max_h:
            widest = max(text_size(draw, line, font)[0] for line in lines)
            if widest <= max_w:
                return font, lines, line_h
        size -= 1
    font = get_font(min_size, bold=bold, family=family)
    lines = wrap_text(draw, text, font, max_w)
    return font, lines, int(min_size * 1.28)


def draw_centred_lines(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    top_y: int,
    lines: Sequence[str],
    font,
    fill,
    line_h: int,
    align: str = "center",
    left_x: int | None = None,
) -> int:
    y = top_y
    for line in lines:
        width, _ = text_size(draw, line, font)
        if align == "center":
            x = int(center_x - width / 2)
        else:
            x = left_x if left_x is not None else center_x
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y


# --------------------------------------------------------------------------- #
# Style rendering
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=8)
def _halftone_mask(size: tuple[int, int], spacing: int, dot: int) -> Image.Image:
    width, height = size
    yy, xx = np.mgrid[0:height, 0:width]
    pattern = ((xx % spacing) < dot) & ((yy % spacing) < dot)
    return Image.fromarray(np.where(pattern, 0, 255).astype("uint8"), mode="L")


def apply_halftone(image: Image.Image, spacing: int = 6, dot: int = 2, strength: float = 0.18) -> Image.Image:
    mask = _halftone_mask(image.size, spacing, dot)
    darkened = Image.composite(Image.new("RGB", image.size, (0, 0, 0)), image, mask)
    return Image.blend(image, darkened, strength)


def tint(image: Image.Image, colour: tuple[int, int, int], strength: float) -> Image.Image:
    overlay = Image.new("RGB", image.size, colour)
    return Image.blend(image, overlay, max(0.0, min(1.0, strength)))


def enhance_colour(image: Image.Image, factor: float) -> Image.Image:
    return ImageEnhance.Color(image).enhance(factor)


def enhance_contrast(image: Image.Image, factor: float) -> Image.Image:
    return ImageEnhance.Contrast(image).enhance(factor)


def enhance_sharpness(image: Image.Image, factor: float) -> Image.Image:
    return ImageEnhance.Sharpness(image).enhance(factor)


def style_filter(image: Image.Image, style: str) -> Image.Image:
    """Push an image toward the visual language of a style preset."""
    style = (style or "manga").lower()

    if style == "manga":
        gray = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=2)
        gray = ImageOps.posterize(gray, 4)
        gray = gray.filter(ImageFilter.SHARPEN)
        return apply_halftone(gray.convert("RGB"), spacing=5, dot=2, strength=0.22)

    if style == "anime":
        out = ImageOps.autocontrast(image, cutoff=1)
        out = enhance_colour(out, 1.35)
        out = enhance_contrast(out, 1.10)
        return enhance_sharpness(out, 1.25)

    if style == "manhwa":
        out = image.filter(ImageFilter.GaussianBlur(0.6))
        out = enhance_colour(out, 1.05)
        return tint(out, (60, 80, 130), 0.10)

    if style == "bengali_comic":
        out = ImageOps.autocontrast(image, cutoff=1)
        out = ImageOps.posterize(out, 3)
        out = enhance_contrast(out, 1.15)
        return tint(out, (150, 90, 40), 0.10)

    if style == "marvel_like":
        out = ImageOps.autocontrast(image, cutoff=1)
        out = ImageOps.posterize(out, 3)
        out = enhance_colour(out, 1.30)
        out = enhance_contrast(out, 1.30)
        return apply_halftone(out, spacing=8, dot=3, strength=0.16)

    if style == "dc_like":
        out = enhance_colour(ImageOps.autocontrast(image, cutoff=1), 0.45)
        out = enhance_contrast(out, 1.35)
        return tint(out, (20, 30, 45), 0.12)

    return image


def vignette(image: Image.Image, strength: float = 0.35) -> Image.Image:
    width, height = image.size
    yy, xx = np.mgrid[0:height, 0:width]
    cx, cy = width / 2.0, height / 2.0
    max_d = ((cx**2 + cy**2) ** 0.5) or 1.0
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max_d
    factor = np.clip(1.0 - strength * (dist**2), 0.0, 1.0)
    arr = np.asarray(image).astype(np.float32) * factor[..., None]
    return Image.fromarray(arr.clip(0, 255).astype("uint8"), mode="RGB")


def gradient(
    size: tuple[int, int],
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
    diagonal: bool = False,
) -> Image.Image:
    width, height = size
    if diagonal:
        ramp = np.linspace(0.0, 1.0, width + height)[:height][:, None]
        xx = np.linspace(0.0, 1.0, width)[None, :]
        t = np.clip((ramp + xx) / 2.0, 0.0, 1.0)
    else:
        t = np.linspace(0.0, 1.0, height)[:, None] * np.ones((1, width))
    top_arr = np.array(top, dtype=np.float32)
    bottom_arr = np.array(bottom, dtype=np.float32)
    arr = top_arr[None, None, :] * (1 - t[..., None]) + bottom_arr[None, None, :] * t[..., None]
    return Image.fromarray(arr.astype("uint8"), mode="RGB")


# --------------------------------------------------------------------------- #
# Bubbles
# --------------------------------------------------------------------------- #


BUBBLE_STYLES = {
    "rounded": {"radius": 26, "fill": (255, 255, 255), "outline": (20, 20, 20), "width": 4},
    "sharp": {"radius": 6, "fill": (252, 252, 250), "outline": (10, 10, 10), "width": 5},
}


def draw_bubble(
    image: Image.Image,
    text: str,
    box: tuple[int, int, int, int],
    kind: str = "speech",
    bubble_style: str = "rounded",
    font_family: str = "sans",
    accent: tuple[int, int, int] = (20, 20, 20),
    tail: str = "bottom-left",
    start_size: int = 26,
) -> None:
    """Draw a speech / thought / caption / sfx bubble directly onto ``image``."""
    if not text or not text.strip():
        return

    x1, y1, x2, y2 = box
    draw = ImageDraw.Draw(image, "RGBA")
    spec = dict(BUBBLE_STYLES.get(bubble_style, BUBBLE_STYLES["rounded"]))

    if kind in ("narration", "caption"):
        pad = 14
        font, lines, line_h = fit_text(
            draw, text, (x2 - x1 - 2 * pad, y2 - y1 - 2 * pad), start_size - 4,
            family=font_family,
        )
        rect = (x1, y1, x1 + (x2 - x1), y1 + (2 * pad + line_h * len(lines)))
        draw.rectangle(rect, fill=(255, 252, 235, 240), outline=accent, width=3)
        draw_centred_lines(
            draw, (rect[0] + rect[2]) // 2, rect[1] + pad, lines, font, accent, line_h
        )
        return

    if kind == "sfx":
        font, lines, line_h = fit_text(
            draw, text.upper(), (x2 - x1, y2 - y1), start_size + 14, bold=True, family=font_family
        )
        for line in lines:
            width, _ = text_size(draw, line, font)
            draw.text(
                ((x1 + x2) // 2 - width // 2, y1),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=4,
                stroke_fill=accent,
            )
            y1 += line_h
        return

    pad = 18
    font, lines, line_h = fit_text(
        draw, text, (x2 - x1 - 2 * pad, y2 - y1 - 2 * pad), start_size, family=font_family
    )
    text_h = line_h * len(lines)
    height = text_h + 2 * pad
    bubble = (x1, y1, x2, y1 + height)

    if kind == "shout":
        spikes = 14
        points: list[tuple[float, float]] = []
        cx, cy = (bubble[0] + bubble[2]) / 2, (bubble[1] + bubble[3]) / 2
        rx, ry = (bubble[2] - bubble[0]) / 2, (bubble[3] - bubble[1]) / 2
        import math

        for i in range(spikes * 2):
            angle = math.pi * i / spikes - math.pi / 2
            scale = 1.16 if i % 2 == 0 else 0.94
            points.append((cx + rx * scale * math.cos(angle), cy + ry * scale * math.sin(angle)))
        draw.polygon(points, fill=spec["fill"], outline=accent)
    else:
        draw.rounded_rectangle(
            bubble, radius=spec["radius"], fill=spec["fill"], outline=accent, width=spec["width"]
        )
        if kind == "speech":
            tx = bubble[0] + 34 if "left" in tail else bubble[2] - 34
            ty = bubble[3]
            direction = -1 if "left" in tail else 1
            draw.polygon(
                [(tx, ty - 6), (tx + direction * 30, ty + 26), (tx + direction * 12, ty - 6)],
                fill=spec["fill"],
                outline=accent,
            )
        if kind == "thought":
            for i, r in enumerate((10, 7, 5)):
                cx = bubble[0] + 30 + i * 20
                cy = bubble[3] + 16 + i * 12
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=spec["fill"], outline=accent, width=2)

    draw_centred_lines(
        draw,
        (bubble[0] + bubble[2]) // 2,
        bubble[1] + pad,
        lines,
        font,
        accent,
        line_h,
    )


def draw_border(image: Image.Image, colour: tuple[int, int, int] = (15, 15, 18), width: int = 6) -> None:
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for i in range(width):
        draw.rectangle((i, i, w - 1 - i, h - 1 - i), outline=colour)


def fit_cover(image: Image.Image, size: tuple[int, int], centering: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    return ImageOps.fit(image, size, method=Image.LANCZOS, centering=centering)


def dominant_color(image: Image.Image) -> tuple[int, int, int]:
    small = image.convert("RGB").resize((32, 32), Image.LANCZOS)
    arr = np.asarray(small).reshape(-1, 3).astype(np.float32)
    # weight toward saturated pixels so clothing/skin beats a white background
    sat = arr.max(axis=1) - arr.min(axis=1)
    weights = sat + 1.0
    avg = (arr * weights[:, None]).sum(axis=0) / weights.sum()
    return tuple(int(v) for v in avg)  # type: ignore[return-value]


def placeholder_portrait(
    size: tuple[int, int],
    colour: tuple[int, int, int],
    emotion: str = "neutral",
    name: str = "",
) -> Image.Image:
    """A drawn stand-in figure for characters with no reference image."""
    width, height = size
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    dark = mix(colour, (0, 0, 0), 0.55)
    light = mix(colour, (255, 255, 255), 0.25)

    head_r = int(width * 0.22)
    head_cx, head_cy = width // 2, int(height * 0.20)
    draw.ellipse(
        (head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r),
        fill=light,
        outline=dark,
        width=3,
    )
    # shoulders / torso
    torso_top = head_cy + head_r - 6
    draw.polygon(
        [
            (head_cx - int(width * 0.34), height),
            (head_cx - int(width * 0.20), torso_top),
            (head_cx + int(width * 0.20), torso_top),
            (head_cx + int(width * 0.34), height),
        ],
        fill=colour,
        outline=dark,
    )

    # expression
    eye_dx = int(head_r * 0.42)
    eye_y = head_cy - int(head_r * 0.10)
    eye_r = max(2, head_r // 7)
    for sign in (-1, 1):
        draw.ellipse(
            (
                head_cx + sign * eye_dx - eye_r,
                eye_y - eye_r,
                head_cx + sign * eye_dx + eye_r,
                eye_y + eye_r,
            ),
            fill=dark,
        )
    mouth_w = int(head_r * 0.60)
    mouth_y = head_cy + int(head_r * 0.42)
    if emotion in ("joy", "love"):
        draw.arc(
            (head_cx - mouth_w // 2, mouth_y - mouth_w // 3, head_cx + mouth_w // 2, mouth_y + mouth_w // 3),
            start=10,
            end=170,
            fill=dark,
            width=3,
        )
    elif emotion in ("sadness", "fear"):
        draw.arc(
            (head_cx - mouth_w // 2, mouth_y, head_cx + mouth_w // 2, mouth_y + mouth_w // 2),
            start=190,
            end=350,
            fill=dark,
            width=3,
        )
    elif emotion in ("anger", "determination"):
        draw.line((head_cx - mouth_w // 2, mouth_y + 4, head_cx + mouth_w // 2, mouth_y + 4), fill=dark, width=4)
        for sign in (-1, 1):
            draw.line(
                (
                    head_cx + sign * eye_dx - sign * eye_r * 2,
                    eye_y - eye_r * 3,
                    head_cx + sign * eye_dx + sign * eye_r * 2,
                    eye_y - eye_r * 2,
                ),
                fill=dark,
                width=3,
            )
    elif emotion == "surprise":
        draw.ellipse(
            (head_cx - mouth_w // 4, mouth_y - mouth_w // 4, head_cx + mouth_w // 4, mouth_y + mouth_w // 4),
            outline=dark,
            width=3,
        )
    else:
        draw.line((head_cx - mouth_w // 2, mouth_y, head_cx + mouth_w // 2, mouth_y), fill=dark, width=3)

    if name:
        font = get_font(max(11, width // 14), bold=True)
        text_w, _ = text_size(draw, name, font)
        draw.text(
            (head_cx - text_w // 2, height - 22),
            name,
            font=font,
            fill=(255, 255, 255),
            stroke_width=3,
            stroke_fill=(0, 0, 0),
        )
    return canvas


def paste_rgba(base: Image.Image, overlay: Image.Image, position: tuple[int, int]) -> None:
    if overlay.mode != "RGBA":
        overlay = overlay.convert("RGBA")
    base.paste(overlay, position, overlay)


def apply_preset_to_image(image: Image.Image, style: str) -> Image.Image:
    preset = get_style_preset(style)
    return style_filter(image, preset.id)


def palette_gradient(style: str, size: tuple[int, int], shift: float = 0.0) -> Image.Image:
    preset = get_style_preset(style)
    palette = [hex_to_rgb(c) for c in (preset.palette or ["#222222", "#dddddd"])]
    top = palette[0] if palette else (30, 30, 30)
    bottom = palette[min(2, len(palette) - 1)] if palette else (200, 200, 200)
    if shift:
        top = mix(top, palette[-1], shift * 0.5)
        bottom = mix(bottom, palette[1 % len(palette)], shift * 0.5)
    return gradient(size, top, bottom, diagonal=True)


def iter_chunks(seq: Sequence, size: int) -> Iterable[Sequence]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
