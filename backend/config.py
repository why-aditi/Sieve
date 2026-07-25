"""Environment loading — one place, imported by every module that reads env.

Previously each module called os.getenv() and only normalize.py loaded .env, so
whether the LLM worked depended on import order: importing adapters without
normalize left GROQ_API_KEY unset and every fallback silently no-opped with no
error anywhere. Load once, here.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Absent .env is not an error — Render injects real env vars and has no file.
load_dotenv(Path(__file__).resolve().parent / ".env")

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# The SDK ships a 60s read timeout and 2 retries — up to ~3 minutes of hanging
# before our fallback ever runs, on a path a user is waiting on. Every LLM call
# here is optional by construction (§2: each has a non-LLM fallback), so a slow
# answer is worth strictly less than a fast miss.
GROQ_TIMEOUT_SECONDS = 6.0
GROQ_MAX_RETRIES = 1        # one retry, then fall back


def groq_key() -> str | None:
    """Read at call time, not import time, so tests can monkeypatch it."""
    return os.getenv("GROQ_API_KEY") or None


def groq_client():
    """The only place a Groq client is constructed.

    Raises if the SDK is missing or the key is unset — callers already treat
    any exception as "use the deterministic result".
    """
    from groq import Groq

    return Groq(timeout=GROQ_TIMEOUT_SECONDS, max_retries=GROQ_MAX_RETRIES)
