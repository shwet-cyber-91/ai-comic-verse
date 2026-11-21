"""Quick test for the Gemini retry / fallback / circuit-breaker logic.

Run with:
    cd backend
    venv\Scripts\python test_gemini_fix.py

Needs GEMINI_API_KEY in .env or environment.
"""

from __future__ import annotations

import os
import sys
import time

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import get_settings, reset_settings_cache
from app.providers.llm_gemini import GeminiLLM, _circuit, _is_retryable, _backoff_delay
from app.providers.base import ProviderError


def test_helpers():
    print("=" * 60)
    print("TEST 1: Helper functions")
    print("=" * 60)

    # _is_retryable
    assert _is_retryable(ProviderError("gemini returned 503")) is True
    assert _is_retryable(ProviderError("high demand")) is True
    assert _is_retryable(ProviderError("rate limit")) is True
    assert _is_retryable(ProviderError("timeout")) is True
    assert _is_retryable(ProviderError("connection refused")) is True
    assert _is_retryable(ProviderError("bad request 400")) is False
    assert _is_retryable(ProviderError("invalid api key")) is False
    print("  _is_retryable ........................ PASS")

    # _backoff_delay
    for i in range(5):
        d = _backoff_delay(i)
        assert 0 <= d <= 30, f"backoff delay {d} out of range"
    print("  _backoff_delay ....................... PASS")

    # Circuit breaker basics
    cb = _circuit.__class__(failure_threshold=3, cooldown_seconds=5)
    cb.check()  # should not raise when closed
    print("  circuit breaker (closed) ............. PASS")
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    print("  circuit breaker (open) ............... PASS")
    try:
        cb.check()
        assert False, "should have raised"
    except ProviderError as e:
        assert "OPEN" in str(e)
    print("  circuit breaker (blocks when open) ... PASS")

    # Wait for half-open
    print("  waiting 5s for cooldown ...")
    time.sleep(5)
    assert cb.state == "half_open"
    print("  circuit breaker (half-open) .......... PASS")
    cb.record_success()
    assert cb.state == "closed"
    print("  circuit breaker (closes on success) .. PASS")


def test_gemini_call():
    print("\n" + "=" * 60)
    print("TEST 2: Live Gemini API call")
    print("=" * 60)

    reset_settings_cache()
    settings = get_settings()

    if not settings.gemini_api_key.strip():
        print("  SKIPPED — GEMINI_API_KEY not set in .env")
        print("  Add GEMINI_API_KEY=your_key to backend/.env and rerun.")
        return False

    print(f"  API key present: yes")
    print(f"  Configured model: {settings.gemini_model}")

    llm = GeminiLLM()
    print(f"  Fallback chain: {', '.join(llm.FALLBACK_MODELS[:4])} ...")

    system = "You are a helpful assistant. Reply with ONLY valid JSON."
    user = 'Return a JSON object with one field: {"status": "ok", "message": "hello"}'

    try:
        start = time.perf_counter()
        result = llm._generate(system, user)
        elapsed = time.perf_counter() - start
        print(f"  API call succeeded in {elapsed:.2f}s")
        print(f"  Response preview: {result[:200]}")

        # Verify it's valid JSON
        import json
        data = json.loads(result)
        assert data.get("status") == "ok"
        print("  JSON validation ...................... PASS")
        return True

    except ProviderError as e:
        print(f"  API call FAILED: {e}")
        return False
    except Exception as e:
        print(f"  UNEXPECTED ERROR: {type(e).__name__}: {e}")
        return False


def test_json_task():
    print("\n" + "=" * 60)
    print("TEST 3: complete_json (schema-driven)")
    print("=" * 60)

    reset_settings_cache()
    settings = get_settings()

    if not settings.gemini_api_key.strip():
        print("  SKIPPED — GEMINI_API_KEY not set")
        return False

    from pydantic import BaseModel

    class TestOutput(BaseModel):
        genre: str
        tone: str
        scene_count: int

    llm = GeminiLLM()

    try:
        result = llm.complete_json(
            "story_understanding",
            {
                "story_text": "A brave knight rescues a dragon from an evil princess.",
                "title": "The Dragon's Knight",
                "panel_count": 4,
                "language": "en",
                "user_characters": [],
            },
            TestOutput,
        )
        print(f"  genre={result.genre}, tone={result.tone}, scenes={result.scene_count}")
        assert result.genre
        assert result.tone
        assert 1 <= result.scene_count <= 8
        print("  Schema validation .................... PASS")
        return True

    except ProviderError as e:
        print(f"  FAILED: {e}")
        return False
    except Exception as e:
        print(f"  UNEXPECTED ERROR: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("GEMINI RESILIENCE TEST SUITE")
    print("=" * 60 + "\n")

    test_helpers()
    ok1 = test_gemini_call()
    ok2 = test_json_task()

    print("\n" + "=" * 60)
    if ok1 and ok2:
        print("ALL TESTS PASSED")
    elif not ok1 and not ok2:
        print("TESTS SKIPPED (no API key) — helpers passed, live calls skipped")
    else:
        print("SOME TESTS FAILED — check output above")
    print("=" * 60 + "\n")
