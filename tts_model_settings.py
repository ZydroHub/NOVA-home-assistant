"""Selectable Piper voice-quality definitions and persisted preference."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import threading

from config import TTS_SETTINGS_FILE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TtsVoiceSpec:
    id: str
    label: str
    model_name: str
    description: str
    size_note: str

    def to_public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "size_note": self.size_note,
        }


DEFAULT_TTS_VOICE_ID = "high"
TTS_VOICES: tuple[TtsVoiceSpec, ...] = (
    TtsVoiceSpec(
        id="low",
        label="Low",
        model_name="en_US-lessac-low",
        description="Fastest voice generation.",
        size_note="Lowest quality",
    ),
    TtsVoiceSpec(
        id="medium",
        label="Medium",
        model_name="en_US-lessac-medium",
        description="Balanced speed and clarity.",
        size_note="Balanced",
    ),
    TtsVoiceSpec(
        id="high",
        label="High",
        model_name="en_US-lessac-high",
        description="Clearest and most natural voice.",
        size_note="Best quality",
    ),
)
_VOICES_BY_ID = {voice.id: voice for voice in TTS_VOICES}


def get_tts_voice_spec(voice_id: str) -> TtsVoiceSpec:
    try:
        return _VOICES_BY_ID[voice_id]
    except KeyError as exc:
        allowed = ", ".join(_VOICES_BY_ID)
        raise ValueError(f"Unknown voice quality '{voice_id}'. Allowed: {allowed}.") from exc


def get_tts_voice_options() -> list[dict[str, str]]:
    return [voice.to_public_dict() for voice in TTS_VOICES]


class TtsVoiceSettingsStore:
    """Thread-safe, atomic persistence for the selected Piper voice quality."""

    def __init__(self, path: str | os.PathLike[str] | None = None, *, persist: bool = True) -> None:
        self.path = Path(path or TTS_SETTINGS_FILE)
        self.persist = persist
        self._lock = threading.Lock()
        self._selected_voice = DEFAULT_TTS_VOICE_ID
        self._load()

    def get_selected_voice(self) -> str:
        with self._lock:
            return self._selected_voice

    def set_selected_voice(self, voice_id: str) -> str:
        get_tts_voice_spec(voice_id)
        with self._lock:
            self._selected_voice = voice_id
            self._save_locked()
            return self._selected_voice

    def _load(self) -> None:
        if not self.persist or not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            selected_voice = payload.get("selected_voice") if isinstance(payload, dict) else None
            if isinstance(selected_voice, str):
                get_tts_voice_spec(selected_voice)
                self._selected_voice = selected_voice
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("TTS voice settings load failed; using default: %s", exc)

    def _save_locked(self) -> None:
        if not self.persist:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
            with temporary_path.open("w", encoding="utf-8") as handle:
                json.dump({"selected_voice": self._selected_voice}, handle, indent=2, sort_keys=True)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            logger.warning("TTS voice settings save failed: %s", exc)


_tts_voice_settings_store: TtsVoiceSettingsStore | None = None


def get_tts_voice_settings_store() -> TtsVoiceSettingsStore:
    global _tts_voice_settings_store
    if _tts_voice_settings_store is None:
        _tts_voice_settings_store = TtsVoiceSettingsStore()
    return _tts_voice_settings_store
