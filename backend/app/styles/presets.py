"""Style presets.

Every preset describes a *generic visual language* - line weight, palette,
shading, panel conventions. None of them name, depict or imitate a specific
copyrighted character or living artist, per the brief.
"""

from __future__ import annotations

from ..schemas import StylePreset

STYLE_PRESETS: dict[str, StylePreset] = {
    "manga": StylePreset(
        id="manga",
        name="Manga",
        description="High-contrast black and white, screentone shading, dramatic speed lines.",
        prompt_fragment=(
            "black and white manga panel, crisp confident ink lineart, screentone shading, "
            "high contrast, dramatic speed lines and radial focus lines, expressive large eyes, "
            "clean uncluttered backgrounds, printed comic texture"
        ),
        negative_fragment="colour, full colour, painterly, soft airbrush, 3d render, photo",
        palette=["#111111", "#3d3d3d", "#8a8a8a", "#d8d8d8", "#f7f5f0"],
        bubble_style="sharp",
        font_family="sans",
        line_weight="bold",
        best_for=["action", "drama", "horror"],
    ),
    "anime": StylePreset(
        id="anime",
        name="Anime",
        description="Vivid cel-shaded colour, clean lineart, glossy highlights, expressive faces.",
        prompt_fragment=(
            "cel-shaded anime illustration, clean crisp lineart, vivid saturated colours, "
            "two-tone shadow with solid terminator line, glossy highlights, expressive eyes, "
            "detailed hair strands, bright background with bokeh"
        ),
        negative_fragment="photorealistic, sketch, rough pencil, monochrome, muddy colours",
        palette=["#1b2a4a", "#2f6fb5", "#f2b23e", "#e8604c", "#f4f7fb"],
        bubble_style="rounded",
        font_family="sans",
        line_weight="medium",
        best_for=["adventure", "school life", "romance"],
    ),
    "manhwa": StylePreset(
        id="manhwa",
        name="Manhwa",
        description="Vertical-scroll friendly, soft gradient shading, tall elegant figures.",
        prompt_fragment=(
            "korean webtoon manhwa illustration, soft gradient cel shading, tall elegant figure "
            "proportions, delicate lineart, pastel-to-cool colour range, glowing rim light, "
            "polished digital finish, tall vertical composition"
        ),
        negative_fragment="harsh hatching, low resolution, rough sketch, heavy ink texture",
        palette=["#20243b", "#4b5a8a", "#a8b6de", "#e2c9a0", "#fbfcff"],
        bubble_style="rounded",
        font_family="sans",
        line_weight="thin",
        best_for=["fantasy", "romance", "portal fantasy"],
    ),
    "bengali_comic": StylePreset(
        id="bengali_comic",
        name="Bengali Comic",
        description="Bold flat colour, strong outlines, hand-lettered feel, folk-motif detail.",
        prompt_fragment=(
            "Bengali-language South Asian comic illustration, hand-inked bold confident outlines, "
            "flat warm terracotta and ochre colour blocks with indigo accents, hand-printed paper "
            "texture, Bengali folk-art inspired motifs in the environment, expressive natural faces, "
            "vintage Bengali comic-book print grain, readable uncluttered composition"
        ),
        negative_fragment="anime moe, glossy 3d, photorealistic, neon cyberpunk",
        palette=["#7a2f1f", "#c9642c", "#e0a83e", "#2b4a6f", "#f6ecd8"],
        bubble_style="rounded",
        font_family="serif",
        line_weight="bold",
        best_for=["social drama", "folklore", "slice of life"],
    ),
    "marvel_like": StylePreset(
        id="marvel_like",
        name="Superhero (western)",
        description="Dynamic anatomy, heavy rendering, cross-hatching, dramatic light, ink+colour.",
        prompt_fragment=(
            "western superhero comic art, dynamic exaggerated anatomy, heavy ink rendering with "
            "cross-hatching and spot blacks, dramatic single-source lighting, muscular silhouettes, "
            "cinematic low-angle hero poses, halftone dot colour texture, bold saturated primaries"
        ),
        negative_fragment="chibi, flat minimal lineart, pastel, watercolour, shojo",
        palette=["#12244a", "#d22b2b", "#f5c518", "#1a1a1a", "#e9eef5"],
        bubble_style="sharp",
        font_family="sans",
        line_weight="bold",
        best_for=["action", "superhero", "sci-fi"],
    ),
    "dc_like": StylePreset(
        id="dc_like",
        name="Noir (western)",
        description="Moody realism, deep shadows, muted palette, gritty texture, cinematic panels.",
        prompt_fragment=(
            "noir western comic art, moody semi-realistic rendering, deep chiaroscuro shadows, "
            "muted desaturated palette with one accent colour, gritty film-grain texture, "
            "cinematic widescreen staging, restrained confident lineart"
        ),
        negative_fragment="bright saturated cartoon, chibi, kawaii, flat vector, cheerful pastel",
        palette=["#0e1116", "#2c3440", "#5c6b7a", "#b98a4b", "#d9dee4"],
        bubble_style="sharp",
        font_family="sans",
        line_weight="medium",
        best_for=["crime", "mystery", "thriller"],
    ),
}

DEFAULT_STYLE = "manga"


def get_style_preset(style: str | None) -> StylePreset:
    if not style:
        return STYLE_PRESETS[DEFAULT_STYLE]
    return STYLE_PRESETS.get(style, STYLE_PRESETS[DEFAULT_STYLE])


def list_style_presets() -> list[StylePreset]:
    return list(STYLE_PRESETS.values())


def style_palette(style: str | None) -> list[str]:
    return get_style_preset(style).palette
