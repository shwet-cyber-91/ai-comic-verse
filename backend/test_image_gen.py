"""Quick test for Gemini image generation.

Run on YOUR machine:
    venv\Scripts\python test_image_gen.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import get_settings, reset_settings_cache
from app.providers.image_gemini import GeminiImageProvider, IMAGE_MODEL_CHAIN
from app.providers.base import ImageRequest, ProviderError


def main():
    reset_settings_cache()
    settings = get_settings()

    print("=" * 60)
    print("GEMINI IMAGE GENERATION TEST")
    print("=" * 60)
    print(f"API Key: {settings.gemini_api_key[:20]}...")
    print(f"Primary model: {settings.gemini_image_model}")
    print(f"Fallback chain: {IMAGE_MODEL_CHAIN}")
    print(f"Strict mode: {settings.strict_providers}")
    print()

    provider = GeminiImageProvider()

    test_request = ImageRequest(
        panel_id="test_001",
        prompt=(
            "A young woman with long dark hair and amber eyes stands on stone steps "
            "holding a brass lantern, low angle shot, dark gothic tower background, "
            "manga art style, dramatic lighting"
        ),
        negative_prompt="blurry, low quality, blank expression, emotionless",
        style="manga",
        size=768,
        seed=42,
        output_path="storage/tmp/test_panel.png",
        reference_images=[],
        character_names=["Rokeya"],
        action="climbing stone steps with lantern",
        emotion="determination",
        shot="low_angle",
        setting="dark stone tower, night",
        time_of_day="night",
        dialogue_hint="Hold steady. Just a few more steps.",
    )

    start = time.perf_counter()
    try:
        result = provider.generate(test_request)
        elapsed = time.perf_counter() - start
        print(f"SUCCESS in {elapsed:.1f}s")
        print(f"  Provider: {result.provider}")
        print(f"  Path: {result.path}")
        print(f"  Model used: {result.meta.get('model')}")
        print(f"  File size: {os.path.getsize(result.path)} bytes")
    except ProviderError as e:
        elapsed = time.perf_counter() - start
        print(f"FAILED after {elapsed:.1f}s")
        print(f"  Error: {e}")
        print()
        print("Check:")
        print("  1. GEMINI_API_KEY is valid")
        print("  2. GEMINI_IMAGE_MODEL is one of:", IMAGE_MODEL_CHAIN)
        print("  3. Run debug_gemini.py to see available models")
        sys.exit(1)

    print()
    print("=" * 60)
    print("If SUCCESS: image generation is working correctly")
    print("If FAILED:  check the error above and fix .env")
    print("=" * 60)


if __name__ == "__main__":
    main()
