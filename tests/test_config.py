"""Tests for config module (no LLM or server)."""
import os

import pytest


def test_config_loads():
    """Config module loads and exposes expected variables."""
    from config import (
        PORT,
        NOVA_BIND_HOST,
        CONVERSATIONS_FILE,
        TOOLS_PATH,
        JOBS_FILE,
        LOCAL_DIR,
        CHAT_REPO_ID,
        TOOL_REPO_ID,
    )
    assert isinstance(PORT, int)
    assert PORT > 0
    assert NOVA_BIND_HOST == "127.0.0.1"
    assert CONVERSATIONS_FILE.endswith(".json")
    assert TOOLS_PATH.endswith(".json")
    assert JOBS_FILE.endswith(".json")
    assert "models" in LOCAL_DIR or "models" in os.path.normpath(LOCAL_DIR)
    assert "Qwen" in CHAT_REPO_ID
    assert "functiongemma" in TOOL_REPO_ID.lower() or "nlouis" in TOOL_REPO_ID


def test_setup_logging_no_error():
    """setup_logging can be called without error."""
    from config import setup_logging
    setup_logging()
