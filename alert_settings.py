"""Shared alert-region settings for NOVA."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from config import (
    ALERT_SETTINGS_FILE,
    TELEGRAM_NACKA_ENABLED,
    TELEGRAM_STARTUP_NOTIFICATIONS_ENABLED,
    TELEGRAM_STOCKHOLM_ENABLED,
)
from wake_word import DEFAULT_WAKE_COMMAND_MODE, DEFAULT_WAKE_PHRASES, WAKE_COMMAND_MODES, normalize_wake_phrases

logger = logging.getLogger(__name__)

ALERT_REGIONS = ("nacka", "stockholm")
DEFAULT_ALERT_SETTINGS = {
    "nacka": bool(TELEGRAM_NACKA_ENABLED),
    "stockholm": bool(TELEGRAM_STOCKHOLM_ENABLED),
}
DEFAULT_TELEGRAM_SETTINGS = {
    "startup_notifications": bool(TELEGRAM_STARTUP_NOTIFICATIONS_ENABLED),
}
DEFAULT_VOICE_SETTINGS = {
    "language": (os.getenv("WHISPER_LANGUAGE", "en") or "en").strip().lower(),
    "always_listening": True,
    "wake_phrases": list(DEFAULT_WAKE_PHRASES),
    "wake_command_mode": DEFAULT_WAKE_COMMAND_MODE,
}

class AlertSettingsStore:
    """Thread-safe JSON store for alert region toggles."""

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        defaults: dict[str, bool] | None = None,
        persist: bool = True,
    ) -> None:
        self.path = Path(path or ALERT_SETTINGS_FILE)
        self.persist = persist
        self.defaults = self._normalize_payload(defaults or DEFAULT_ALERT_SETTINGS)
        self.telegram_defaults = dict(DEFAULT_TELEGRAM_SETTINGS)
        self.voice_defaults = self._normalize_voice_payload(DEFAULT_VOICE_SETTINGS)
        self._lock = threading.Lock()
        self._settings = dict(self.defaults)
        self._telegram_settings = dict(self.telegram_defaults)
        self._voice_settings = self._copy_voice_settings(self.voice_defaults)
        self._load()

    def get(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._settings)

    def get_telegram(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._telegram_settings)

    def get_voice_settings(self) -> dict[str, object]:
        with self._lock:
            return self._copy_voice_settings(self._voice_settings)

    def is_enabled(self, region: str) -> bool:
        normalized_region = self._normalize_region(region)
        with self._lock:
            return bool(self._settings[normalized_region])

    def startup_notifications_enabled(self) -> bool:
        with self._lock:
            return bool(self._telegram_settings["startup_notifications"])

    def set_region(self, region: str, enabled: bool) -> dict[str, bool]:
        normalized_region = self._normalize_region(region)
        with self._lock:
            self._settings[normalized_region] = bool(enabled)
            self._save_locked()
            return dict(self._settings)

    def set_startup_notifications(self, enabled: bool) -> dict[str, bool]:
        with self._lock:
            self._telegram_settings["startup_notifications"] = self._coerce_bool(enabled)
            self._save_locked()
            return dict(self._telegram_settings)

    def update(self, values: dict[str, object]) -> dict[str, bool]:
        normalized_values = self._normalize_payload(values, allow_partial=True)
        if not normalized_values:
            return self.get()
        with self._lock:
            self._settings.update(normalized_values)
            self._save_locked()
            return dict(self._settings)

    def update_telegram(self, values: dict[str, object]) -> dict[str, bool]:
        normalized_values = self._normalize_telegram_payload(values)
        if not normalized_values:
            return self.get_telegram()
        with self._lock:
            self._telegram_settings.update(normalized_values)
            self._save_locked()
            return dict(self._telegram_settings)

    def update_voice_settings(self, values: dict[str, object]) -> dict[str, object]:
        normalized_values = self._normalize_voice_payload(values, allow_partial=True)
        if not normalized_values:
            return self.get_voice_settings()
        with self._lock:
            self._voice_settings.update(normalized_values)
            self._save_locked()
            return self._copy_voice_settings(self._voice_settings)

    def toggle_region(self, region: str) -> tuple[bool, dict[str, bool]]:
        normalized_region = self._normalize_region(region)
        with self._lock:
            enabled = not bool(self._settings[normalized_region])
            self._settings[normalized_region] = enabled
            self._save_locked()
            return enabled, dict(self._settings)

    def _load(self) -> None:
        if not self.persist or not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Alert settings load failed: %s", exc)
            return

        if isinstance(payload, dict):
            values = payload.get("alerts") if isinstance(payload.get("alerts"), dict) else payload
            try:
                self._settings.update(self._normalize_payload(values, allow_partial=True))
            except ValueError as exc:
                logger.warning("Alert settings ignored invalid region config: %s", exc)
            telegram_values = payload.get("telegram")
            if isinstance(telegram_values, dict):
                self._telegram_settings.update(self._normalize_telegram_payload(telegram_values))
            voice_values = payload.get("voice")
            if isinstance(voice_values, dict):
                try:
                    self._voice_settings.update(self._normalize_voice_payload(voice_values, allow_partial=True))
                except ValueError as exc:
                    logger.warning("Alert settings ignored invalid voice config: %s", exc)

    def _save_locked(self) -> None:
        if not self.persist:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            payload = {
                "alerts": dict(self._settings),
                "telegram": dict(self._telegram_settings),
                "voice": self._copy_voice_settings(self._voice_settings),
            }
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            os.replace(temp_path, self.path)
        except OSError as exc:
            logger.warning("Alert settings save failed: %s", exc)

    def _normalize_payload(self, payload: dict[str, object], *, allow_partial: bool = False) -> dict[str, bool]:
        result = {} if allow_partial else {region: True for region in ALERT_REGIONS}
        for region, value in payload.items():
            normalized_region = self._normalize_region(str(region))
            result[normalized_region] = self._coerce_bool(value)
        if not allow_partial:
            for region in ALERT_REGIONS:
                result.setdefault(region, True)
        return result

    def _normalize_telegram_payload(self, payload: dict[str, object]) -> dict[str, bool]:
        result: dict[str, bool] = {}
        if "startup_notifications" in payload:
            result["startup_notifications"] = self._coerce_bool(payload["startup_notifications"])
        return result

    def _normalize_voice_payload(self, payload: dict[str, object], *, allow_partial: bool = False) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("Voice settings payload must be an object.")
        result: dict[str, object] = {} if allow_partial else {
            "language": "en",
            "always_listening": True,
            "wake_phrases": list(DEFAULT_WAKE_PHRASES),
            "wake_command_mode": DEFAULT_WAKE_COMMAND_MODE,
        }
        if "language" in payload:
            result["language"] = self._normalize_voice_language(payload["language"])
        elif not allow_partial:
            result["language"] = "en"
        if "always_listening" in payload:
            result["always_listening"] = self._coerce_bool(payload["always_listening"])
        elif not allow_partial:
            result["always_listening"] = True
        if "wake_phrases" in payload:
            result["wake_phrases"] = self._normalize_wake_phrases(payload["wake_phrases"])
        elif not allow_partial:
            result["wake_phrases"] = list(DEFAULT_WAKE_PHRASES)
        if "wake_command_mode" in payload:
            result["wake_command_mode"] = self._normalize_wake_command_mode(payload["wake_command_mode"])
        elif not allow_partial:
            result["wake_command_mode"] = DEFAULT_WAKE_COMMAND_MODE
        return result

    def _copy_voice_settings(self, settings: dict[str, object]) -> dict[str, object]:
        return {
            "language": self._normalize_voice_language(settings.get("language", "en")),
            "always_listening": self._coerce_bool(settings.get("always_listening", True)),
            "wake_phrases": self._normalize_wake_phrases(settings.get("wake_phrases", DEFAULT_WAKE_PHRASES)),
            "wake_command_mode": self._normalize_wake_command_mode(settings.get("wake_command_mode", DEFAULT_WAKE_COMMAND_MODE)),
        }

    @staticmethod
    def _normalize_voice_language(value: object) -> str:
        normalized = str(value or "").strip().lower().replace("_", "-")
        aliases = {
            "": "auto",
            "none": "auto",
            "detect": "auto",
            "automatic": "auto",
            "english": "en",
            "eng": "en",
            "us": "en",
            "en-us": "en",
            "en-gb": "en",
            "swedish": "sv",
            "svenska": "sv",
            "swe": "sv",
            "se": "sv",
            "sv-se": "sv",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"auto", "en", "sv"}:
            raise ValueError("Voice language must be 'auto', 'en', or 'sv'.")
        return normalized

    @staticmethod
    def _normalize_wake_phrases(value: object) -> list[str]:
        phrases = normalize_wake_phrases(value)
        for phrase in normalize_wake_phrases(DEFAULT_WAKE_PHRASES):
            if phrase not in phrases:
                phrases.append(phrase)
        if len(phrases) > 32:
            phrases = phrases[:32]
        if any(len(phrase) > 48 for phrase in phrases):
            raise ValueError("Wake phrases must be 48 characters or shorter.")
        return phrases

    @staticmethod
    def _normalize_wake_command_mode(value: object) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_")
        if normalized not in WAKE_COMMAND_MODES:
            allowed = ", ".join(sorted(WAKE_COMMAND_MODES))
            raise ValueError(f"Wake command mode must be one of: {allowed}.")
        return normalized

    @staticmethod
    def _normalize_region(region: str) -> str:
        normalized_region = (region or "").strip().lower()
        if normalized_region not in ALERT_REGIONS:
            raise ValueError("Alert region must be 'nacka' or 'stockholm'.")
        return normalized_region

    @staticmethod
    def _coerce_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "enabled"}:
                return True
            if normalized in {"0", "false", "no", "off", "disabled"}:
                return False
        return bool(value)


_alert_settings_store: AlertSettingsStore | None = None


def get_alert_settings_store() -> AlertSettingsStore:
    global _alert_settings_store
    if _alert_settings_store is None:
        _alert_settings_store = AlertSettingsStore()
    return _alert_settings_store
