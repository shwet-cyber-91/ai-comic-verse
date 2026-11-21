"""Test Pollinations image generation.

Run on YOUR machine:
    venv\Scripts\python test_pollinations.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import reset_settings_cache
from app.providers.image_pollinations import PollinationsImageProvider
from app.providers.base import ImageRequest, ProviderError


def main():
    reset_settings_cache()
    print("=" * 60)
    print("POLLINATIONS IMAGE TEST (free, no API key)")
    print("=" * 60)

    provider = PollinationsImageProvider()
    print(f"Model: {provider.model}")
    print(f"Size: {provider.image_size}")
    print()

    req = ImageRequest(
        panel_id="test_001",
        prompt="young woman with long dark hair holding a glowing brass lantern on stone steps of a dark gothic tower",
        negative_prompt="blurry, low quality",
        style="manga",
        size=768,
        seed=42,
        output_path="storage/tmp/test_pollinations.png",
        character_names=["Rokeya"],
        action="climbing stone steps with lantern",
        emotion="determination",
        shot="low_angle",
        setting="dark stone tower, night",
        time_of_day="night",
    )

    print("Built prompt:")
    print(f"  {provider._build_prompt(req)[:200]}...")
    print()
    print("Generating (may take 10-30s)...")

    start = time.perf_counter()
    try:
        result = provider.generate(req)
        elapsed = time.perf_counter() - start
        size = os.path.getsize(result.path)
        print(f"\nSUCCESS in {elapsed:.1f}s")
        print(f"  Provider: {result.provider}")
        print(f"  Path: {result.path}")
        print(f"  Size: {size:,} bytes")
        print(f"  Open the image to check quality!")
    except ProviderError as e:
        elapsed = time.perf_counter() - start
        print(f"\nFAILED after {elapsed:.1f}s: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Image generation working! Now generate a comic from the UI.")
    print("=" * 60)


if __name__ == "__main__":
    main()
