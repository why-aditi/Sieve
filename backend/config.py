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


def groq_key() -> str | None:
    """Read at call time, not import time, so tests can monkeypatch it."""
    return os.getenv("GROQ_API_KEY") or None
