"""Selectable local chat-model definitions and persisted model preference."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import threading

from config import CHAT_FILENAME, CHAT_REPO_ID, LOCAL_DIR, MODEL_SETTINGS_FILE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatModelSpec:
    id: str
    label: str
    repo_id: str
    filename: str
    description: str
    size_note: str

    @property
    def path(self) -> Path:
        return Path(LOCAL_DIR) / self.filename

    def to_public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "size_note": self.size_note,
            "available": self.path.is_file(),
        }


DEFAULT_CHAT_MODEL_ID = "qwen3-0.6b"
CHAT_MODELS: tuple[ChatModelSpec, ...] = (
    ChatModelSpec(
        id="qwen3-0.6b",
        label="Qwen3 0.6B",
        repo_id=CHAT_REPO_ID,
        filename=CHAT_FILENAME,
        description="Fastest and current default.",
        size_note="Smallest download",
    ),
    ChatModelSpec(
        id="llama3.2-1b",
        label="Llama 3.2 1B",
        repo_id="bartowski/Llama-3.2-1B-Instruct-GGUF",
        filename="Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        description="Balanced small model.",
        size_note="Fast on a Pi",
    ),
    ChatModelSpec(
        id="qwen2.5-1.5b",
        label="Qwen 2.5 1.5B",
        repo_id="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        filename="qwen2.5-1.5b-instruct-q4_k_m.gguf",
        description="Smarter medium model.",
        size_note="More memory needed",
    ),
    ChatModelSpec(
        id="llama3.2-3b",
        label="Llama 3.2 3B",
        repo_id="bartowski/Llama-3.2-3B-Instruct-GGUF",
        filename="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        description="Best quality, slower replies.",
        size_note="Slowest option",
    ),
)
_MODELS_BY_ID = {model.id: model for model in CHAT_MODELS}


def get_chat_model_spec(model_id: str) -> ChatModelSpec:
    try:
        return _MODELS_BY_ID[model_id]
    except KeyError as exc:
        allowed = ", ".join(_MODELS_BY_ID)
        raise ValueError(f"Unknown chat model '{model_id}'. Allowed: {allowed}.") from exc


def get_chat_model_options() -> list[dict[str, object]]:
    return [model.to_public_dict() for model in CHAT_MODELS]


class ChatModelSettingsStore:
    """Thread-safe, atomic persistence for the requested chat model."""

    def __init__(self, path: str | os.PathLike[str] | None = None, *, persist: bool = True) -> None:
        self.path = Path(path or MODEL_SETTINGS_FILE)
        self.persist = persist
        self._lock = threading.Lock()
        self._selected_model = DEFAULT_CHAT_MODEL_ID
        self._load()

    def get_selected_model(self) -> str:
        with self._lock:
            return self._selected_model

    def set_selected_model(self, model_id: str) -> str:
        get_chat_model_spec(model_id)
        with self._lock:
            self._selected_model = model_id
            self._save_locked()
            return self._selected_model

    def _load(self) -> None:
        if not self.persist or not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            selected_model = payload.get("selected_model") if isinstance(payload, dict) else None
            if isinstance(selected_model, str):
                get_chat_model_spec(selected_model)
                self._selected_model = selected_model
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Chat model settings load failed; using default: %s", exc)

    def _save_locked(self) -> None:
        if not self.persist:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
            with temporary_path.open("w", encoding="utf-8") as handle:
                json.dump({"selected_model": self._selected_model}, handle, indent=2, sort_keys=True)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            logger.warning("Chat model settings save failed: %s", exc)


_chat_model_settings_store: ChatModelSettingsStore | None = None


def get_chat_model_settings_store() -> ChatModelSettingsStore:
    global _chat_model_settings_store
    if _chat_model_settings_store is None:
        _chat_model_settings_store = ChatModelSettingsStore()
    return _chat_model_settings_store
