"""Debug Gemini API — test different model name formats.

Run on YOUR machine (where the app runs):
    venv\Scripts\python debug_gemini.py
"""
from __future__ import annotations

import json
import os
import sys

import httpx


def load_api_key() -> str:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip().startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("GEMINI_API_KEY", "")


def test_model(api_key: str, model: str) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": "Say 'hello' in one word."}]}],
        "generationConfig": {"maxOutputTokens": 10, "temperature": 0.1},
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, params={"key": api_key}, json=body)
        if resp.status_code == 200:
            data = resp.json()
            text = ""
            for c in data.get("candidates", []):
                for p in c.get("content", {}).get("parts", []):
                    text += p.get("text", "")
            return {"ok": True, "text": text.strip()}
        return {"ok": False, "status": resp.status_code, "body": resp.text[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_models(api_key: str) -> list[str]:
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key, "pageSize": 100},
            )
        data = resp.json()
        models = []
        for m in data.get("models", []):
            name = m.get("name", "").replace("models/", "")
            if "gemini" in name.lower():
                models.append(name)
        return models
    except Exception as e:
        print(f"  Could not list models: {e}")
        return []


if __name__ == "__main__":
    api_key = load_api_key()
    if not api_key:
        print("GEMINI_API_KEY not found!")
        sys.exit(1)

    print("=" * 60)
    print("GEMINI API DEBUG")
    print("=" * 60)
    print(f"\nAPI Key (first 20 chars): {api_key[:20]}...")

    # List available models
    print("\n--- Listing available models ---")
    models = list_models(api_key)
    if models:
        print(f"Found {len(models)} Gemini models:")
        for m in models:
            print(f"  - {m}")
    else:
        print("  No models found (check API key)")

    # Test various name formats
    test_names = [
        "gemini-1.5-pro",
        "gemini-1.5-pro-002",
        "gemini-1.5-flash",
        "gemini-1.5-flash-002",
        "gemini-pro",
        "gemini-pro-vision",
        "gemini-1.0-pro",
    ]

    print("\n--- Testing model names ---")
    for name in test_names:
        result = test_model(api_key, name)
        if result["ok"]:
            print(f"  {name:30} OK -> '{result['text'][:30]}'")
        else:
            status = result.get("status", "ERR")
            err = result.get("body", result.get("error", "unknown"))
            print(f"  {name:30} FAIL ({status}): {err[:100]}")

    print("\n" + "=" * 60)
    print("Use ONLY the names that show 'OK' above in your .env")
    print("=" * 60)
