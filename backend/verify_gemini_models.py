"""Verify Gemini model names are valid via the API.

Run:  python3 verify_gemini_models.py
Needs GEMINI_API_KEY in .env or environment.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_api_key() -> str:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip().startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("GEMINI_API_KEY", "")


def list_models(api_key: str) -> list[dict]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}&pageSize=100"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("models", [])
    except Exception as e:
        print(f"ERROR listing models: {e}")
        return []


def test_model_generate(api_key: str, model: str) -> dict:
    """Try a minimal generateContent call."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": "Say hello in one word."}]}],
        "generationConfig": {"maxOutputTokens": 10, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            text = ""
            for cand in data.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    text += part.get("text", "")
            return {"ok": True, "text": text.strip()}
    except urllib.error.HTTPError as e:
        err = json.loads(e.read().decode()) if e.fp else {}
        return {"ok": False, "status": e.code, "error": err.get("error", {}).get("message", str(e))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    api_key = load_api_key()
    if not api_key:
        print("GEMINI_API_KEY not found in .env or environment")
        sys.exit(1)

    print("=" * 60)
    print("GEMINI MODEL VERIFICATION")
    print("=" * 60)

    # List available models
    print("\n--- Available Models ---")
    models = list_models(api_key)
    gemini_models = [m for m in models if "gemini" in m.get("name", "").lower()]
    print(f"Found {len(gemini_models)} Gemini models:")
    for m in gemini_models[:10]:
        name = m.get("name", "").replace("models/", "")
        print(f"  - {name}")
    if len(gemini_models) > 10:
        print(f"  ... and {len(gemini_models) - 10} more")

    # Test our fallback chain
    test_models = [
        "gemini-1.5-pro",
        "gemini-1.5-pro-latest",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
    ]

    print("\n--- Testing Fallback Chain ---")
    for model in test_models:
        result = test_model_generate(api_key, model)
        if result["ok"]:
            print(f"  {model:35} OK  -> '{result['text'][:30]}'")
        else:
            status = result.get("status", "ERR")
            print(f"  {model:35} FAIL (HTTP {status}): {result.get('error', 'unknown')}")

    print("\n" + "=" * 60)
    print("Update FALLBACK_MODELS in llm_gemini.py with only OK models above.")
    print("=" * 60)
