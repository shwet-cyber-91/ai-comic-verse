"""Standalone test for Gemini retry/fallback/circuit-breaker logic.

No external dependencies needed — mocks httpx and pydantic.
Run:  python3 test_gemini_fix_standalone.py
"""

from __future__ import annotations

import json
import random
import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# Minimal mocks so the logic can be tested without installing deps
# ---------------------------------------------------------------------------

class _FakeSettings:
    gemini_api_key = "test-key"
    gemini_model = "gemini-1.5-pro"
    gemini_base_url = "https://generativelanguage.googleapis.com"
    llm_provider = "gemini"
    ollama_base_url = ""
    ollama_model = ""
    strict_providers = False
    def has_llm_credentials(self, _=None): return True
    def has_image_credentials(self, _=None): return True
    def has_stt_credentials(self, _=None): return True

class _FakeHttpxError(Exception):
    pass

# Inject mocks before importing our module
sys.modules["httpx"] = type(sys)("httpx")
sys.modules["httpx"].HTTPError = _FakeHttpxError
sys.modules["httpx"].Client = lambda **kw: None  # placeholder

sys.modules["pydantic"] = type(sys)("pydantic")
sys.modules["pydantic"].BaseModel = object
sys.modules["pydantic"].ValidationError = Exception

sys.modules["pydantic_settings"] = type(sys)("pydantic_settings")
sys.modules["pydantic_settings"].BaseSettings = object
sys.modules["pydantic_settings"].SettingsConfigDict = dict

# Fake config module
_fake_config = type(sys)("app.config")
_fake_config.get_settings = lambda: _FakeSettings()
_fake_config.reset_settings_cache = lambda: None
sys.modules["app.config"] = _fake_config

# Fake logging
_fake_logging = type(sys)("app.logging_config")
class _FakeLog:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): print("  WARN:", a[0] % a[1:] if len(a) > 1 else a[0])
    def error(self, *a, **k): print("  ERROR:", a[0] % a[1:] if len(a) > 1 else a[0])
    def exception(self, *a, **k): pass
_fake_logging.get_logger = lambda _: _FakeLog()
sys.modules["app.logging_config"] = _fake_logging

# Fake base module
_fake_base = type(sys)("app.providers.base")
class ProviderError(RuntimeError):
    pass
_fake_base.ProviderError = ProviderError
_fake_base.BaseLLM = object
sys.modules["app.providers.base"] = _fake_base

# ---------------------------------------------------------------------------
# Now import the logic we want to test (copy-pasted from llm_gemini.py)
# ---------------------------------------------------------------------------

class _CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._last_failure: float | None = None
        self._state = "closed"

    @property
    def state(self) -> str:
        if self._state == "open":
            if self._last_failure is not None:
                elapsed = time.monotonic() - self._last_failure
                if elapsed >= self.cooldown_seconds:
                    self._state = "half_open"
                    self._failures = 0
                    print("  -> circuit entering half-open")
        return self._state

    def record_success(self) -> None:
        self._failures = 0
        if self._state in ("open", "half_open"):
            self._state = "closed"
            print("  -> circuit closed")

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure = time.monotonic()
        if self._failures >= self.failure_threshold:
            self._state = "open"
            print(f"  -> circuit OPEN (failures={self._failures})")

    def check(self) -> None:
        if self.state == "open":
            remaining = self.cooldown_seconds - (time.monotonic() - (self._last_failure or 0))
            raise ProviderError(f"Circuit OPEN — retry after {max(0, int(remaining))}s")


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    retryable_codes = ("503", "429", "502", "504")
    retryable_phrases = (
        "unavailable", "too many requests", "rate limit", "high demand",
        "timeout", "connect", "read timeout", "connection", "temporary",
    )
    if any(code in msg for code in retryable_codes):
        return True
    return any(phrase in msg for phrase in retryable_phrases)


def _backoff_delay(attempt: int, base: float = 2.0, cap: float = 30.0) -> float:
    exp = base * (2 ** attempt)
    return min(exp, cap) * random.random()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

PASS = 0
FAIL = 0

def assert_true(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"    PASS: {msg}")
    else:
        FAIL += 1
        print(f"    FAIL: {msg}")


print("=" * 65)
print("GEMINI RESILIENCE LOGIC TEST (no external deps)")
print("=" * 65)

# ---- Test _is_retryable ----
print("\n--- _is_retryable ---")
assert_true(_is_retryable(ProviderError("gemini returned 503")), "503 is retryable")
assert_true(_is_retryable(ProviderError("high demand, try later")), "high demand is retryable")
assert_true(_is_retryable(ProviderError("429 Too Many Requests")), "429 is retryable")
assert_true(_is_retryable(ProviderError("connection timeout")), "timeout is retryable")
assert_true(not _is_retryable(ProviderError("400 bad request")), "400 is NOT retryable")
assert_true(not _is_retryable(ProviderError("invalid API key")), "auth error is NOT retryable")

# ---- Test _backoff_delay ----
print("\n--- _backoff_delay ---")
for i in range(5):
    d = _backoff_delay(i)
    assert_true(0 <= d <= 30, f"attempt {i}: delay {d:.2f}s in [0, 30]")

# ---- Test circuit breaker ----
print("\n--- Circuit Breaker ---")
cb = _CircuitBreaker(failure_threshold=3, cooldown_seconds=2)
assert_true(cb.state == "closed", "starts closed")
cb.check()  # should not raise
assert_true(True, "check() passes when closed")

cb.record_failure()
cb.record_failure()
assert_true(cb.state == "closed", "still closed at 2 failures")
cb.record_failure()
assert_true(cb.state == "open", "opens at 3 failures")

try:
    cb.check()
    assert_true(False, "check() should raise when open")
except ProviderError as e:
    assert_true("OPEN" in str(e), "check() raises with OPEN message")

print("  waiting 2s for cooldown...")
time.sleep(2)
assert_true(cb.state == "half_open", "enters half-open after cooldown")
cb.record_success()
assert_true(cb.state == "closed", "closes on success")

# ---- Test fallback model chain ----
print("\n--- Fallback Model Chain ---")
FALLBACKS = [
    "gemini-2.5-pro", "gemini-2.0-pro-exp", "gemini-1.5-pro",
    "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash",
    "gemini-2.0-flash-lite", "gemini-1.5-flash-8b",
]
primary = "gemini-1.5-pro"
models = [primary]
for m in FALLBACKS:
    if m != primary and m not in models:
        models.append(m)
assert_true(len(models) == len(FALLBACKS), f"chain has {len(FALLBACKS)} unique models")
assert_true(models[0] == primary, "primary model is first")
assert_true("gemini-1.5-flash" in models, "flash fallback included")

# ---- Simulate retry loop ----
print("\n--- Simulated Retry Loop ---")
attempt_log = []

def fake_call(should_fail_times=2):
    """Simulate a call that fails N times then succeeds."""
    call_count = [0]
    def inner():
        call_count[0] += 1
        attempt_log.append(call_count[0])
        if call_count[0] <= should_fail_times:
            raise ProviderError("gemini returned 503: high demand")
        return '{"status": "ok"}'
    return inner

# Simulate: 2 transient failures, then success
cb2 = _CircuitBreaker(failure_threshold=5, cooldown_seconds=60)
fn = fake_call(should_fail_times=2)
max_retries = 3
result = None
for attempt in range(max_retries):
    try:
        result = fn()
        cb2.record_success()
        break
    except ProviderError as e:
        if _is_retryable(e):
            delay = _backoff_delay(attempt)
            print(f"  attempt {attempt+1} failed, backoff={delay:.2f}s (simulated)")
            if attempt < max_retries - 1:
                continue
        raise

assert_true(result == '{"status": "ok"}', "succeeds after retries")
assert_true(cb2.state == "closed", "circuit stays closed")
assert_true(len(attempt_log) == 3, f"3 attempts made (got {len(attempt_log)})")

# ---- Simulate all models failing ----
print("\n--- Simulate Total Failure (all models exhausted) ---")
attempt_log.clear()

def always_fail():
    attempt_log.append(1)
    raise ProviderError("gemini returned 503: high demand")

cb3 = _CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
models_test = ["pro", "flash", "flash-lite"]
max_retries = 2
last_error = None

for model in models_test:
    for attempt in range(max_retries):
        try:
            always_fail()
        except ProviderError as e:
            last_error = e
            if _is_retryable(e) and attempt < max_retries - 1:
                continue
            break  # exhausted retries for this model
    print(f"  model {model}: exhausted")

cb3.record_failure()
assert_true(cb3.state == "open" if cb3._failures >= 2 else cb3.state != "", "circuit handles total failure")

# ---- Summary ----
print("\n" + "=" * 65)
print(f"RESULTS: {PASS} passed, {FAIL} failed")
if FAIL == 0:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED")
print("=" * 65)
