"""
Central configuration for NOVA backend.
Reads from environment (and optional .env file) with sensible defaults.
"""
import logging
import os
import secrets
import hmac
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _load_environment_file() -> None:
    if load_dotenv is None:
        return

    project_root = Path(os.getenv("NOVA_PROJECT_ROOT", Path(__file__).resolve().parent)).resolve()
    candidate_paths = [
        Path(os.getenv("NOVA_ENV_PATH", project_root / ".env")),
        project_root / ".env",
    ]
    for candidate in candidate_paths:
        if candidate.exists():
            load_dotenv(dotenv_path=candidate, override=False)
            return

    load_dotenv(dotenv_path=project_root / ".env", override=False)


_load_environment_file()

PROJECT_ROOT = Path(os.getenv("NOVA_PROJECT_ROOT", Path(__file__).resolve().parent)).resolve()


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _csv_env(name: str, default: str = "") -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]

# Server
PORT = int(os.getenv("PORT", "8000"))
NOVA_BIND_HOST = os.getenv("NOVA_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
NOVA_INTERNAL_CONTROL_TOKEN = secrets.token_urlsafe(32)


def is_valid_control_token(token: str | None) -> bool:
    """Compare a caller-supplied local control token without leaking timing data."""
    expected = (NOVA_INTERNAL_CONTROL_TOKEN or "").strip()
    provided = (token or "").strip()
    return bool(expected and provided and hmac.compare_digest(provided, expected))

# Paths (relative to project root)
CONVERSATIONS_FILE = os.getenv("CONVERSATIONS_FILE", str(PROJECT_ROOT / "conversations.json"))
TOOLS_PATH = os.getenv("TOOLS_PATH", str(PROJECT_ROOT / "tools.json"))
JOBS_FILE = os.getenv("JOBS_FILE", str(PROJECT_ROOT / "task_jobs.json"))
LOCAL_DIR = os.getenv("LOCAL_DIR", str(PROJECT_ROOT / "models"))

# Chat LLM (Qwen)
CHAT_REPO_ID = os.getenv("CHAT_REPO_ID", "Qwen/Qwen3-0.6B-GGUF")
CHAT_FILENAME = os.getenv("CHAT_FILENAME", "Qwen3-0.6B-Q8_0.gguf")
CHAT_MODEL_PATH = os.path.join(LOCAL_DIR, CHAT_FILENAME)
MODEL_SETTINGS_FILE = os.getenv("MODEL_SETTINGS_FILE", str(PROJECT_ROOT / "model_settings.json"))

# Tool LLM (Function Gemma)
TOOL_REPO_ID = os.getenv("TOOL_REPO_ID", "nlouis/functiongemma-pocket-q4_k_m")
TOOL_FILENAME = os.getenv("TOOL_FILENAME", "functiongemma-pocket-q4_k_m.gguf")
TOOL_MODEL_PATH = os.path.join(LOCAL_DIR, TOOL_FILENAME)

# Telegram bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_SUBSCRIPTIONS_FILE = os.getenv("TELEGRAM_SUBSCRIPTIONS_FILE", str(PROJECT_ROOT / "telegram_subscriptions.json"))
ALERT_SETTINGS_FILE = os.getenv("ALERT_SETTINGS_FILE", str(PROJECT_ROOT / "alert_settings.json"))
TELEGRAM_POLL_INTERVAL_SECONDS = int(os.getenv("TELEGRAM_POLL_INTERVAL_SECONDS", "60"))
TELEGRAM_REQUEST_TIMEOUT_SECONDS = int(os.getenv("TELEGRAM_REQUEST_TIMEOUT_SECONDS", "10"))
TELEGRAM_MAX_RETRIES = int(os.getenv("TELEGRAM_MAX_RETRIES", "3"))
TELEGRAM_NACKA_ENABLED = _env_flag("TELEGRAM_NACKA_ENABLED", True)
TELEGRAM_STOCKHOLM_ENABLED = _env_flag("TELEGRAM_STOCKHOLM_ENABLED", True)
TELEGRAM_STARTUP_NOTIFICATIONS_ENABLED = _env_flag("TELEGRAM_STARTUP_NOTIFICATIONS_ENABLED", True)

# Local hardware controls
NOVA_AUDIO_RELEASE_COMMANDS = os.getenv("NOVA_AUDIO_RELEASE_COMMANDS", "").strip()

# Logging (console only)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def setup_logging() -> None:
    """Configure root logger for console output only. Call once at app startup."""
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
