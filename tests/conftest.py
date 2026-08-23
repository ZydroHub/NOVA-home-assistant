"""
Pytest configuration and fixtures for NOVA backend tests.
Set SKIP_MODEL_LOAD so startup does not load LLM (faster tests).
"""
import os
import sys
import tempfile
from pathlib import Path

# Add project root so "from chat_ai import ..." and "from config import ..." work
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pytest

# Skip loading models when running tests (set before app import)
os.environ["SKIP_MODEL_LOAD"] = "1"

# Use a temp file for conversations in API tests so we don't touch project data
_temp_conv_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
_temp_conv_file.write("[]")
_temp_conv_file.close()
os.environ["CONVERSATIONS_FILE"] = _temp_conv_file.name

_temp_alert_settings_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
_temp_alert_settings_file.write('{"alerts": {"nacka": true, "stockholm": true}, "telegram": {"startup_notifications": true}}')
_temp_alert_settings_file.close()
os.environ["ALERT_SETTINGS_FILE"] = _temp_alert_settings_file.name

_temp_model_settings_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
_temp_model_settings_file.write("{}")
_temp_model_settings_file.close()
os.environ["MODEL_SETTINGS_FILE"] = _temp_model_settings_file.name


@pytest.fixture
def temp_storage_path():
    """A temporary file path for conversation storage (cleaned up after test)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("[]")
        path = f.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass
