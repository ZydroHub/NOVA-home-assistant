"""Wake-word matching helpers for NOVA's always-listening voice mode."""
from __future__ import annotations

from dataclasses import dataclass
import re
import time
from collections.abc import Callable, Iterable


DEFAULT_WAKE_PHRASES = (
    "nova",
    "no va",
    "noah",
    "novah",
    "hey nova",
    "hej nova",
    "hay nova",
    "hey no va",
    "hey noah",
    "hej noah",
    "hay noah",
    "hi nova",
    "hi noah",
    "hello nova",
    "hello noah",
    "ok nova",
    "okay nova",
    "ok noah",
    "okay noah",
    "yo nova",
    "yo noah",
)
DEFAULT_WAKE_COMMAND_MODE = "direct_or_listen"
WAKE_COMMAND_MODES = {DEFAULT_WAKE_COMMAND_MODE}


def normalize_text(text: object) -> str:
    """Normalize speech transcripts for stable wake-word matching."""
    normalized = str(text or "").lower()
    normalized = re.sub(r"[^\w'\s]+", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def normalize_wake_phrases(phrases: object) -> list[str]:
    """Accept a phrase list or comma-separated string and return unique normalized phrases."""
    if phrases is None:
        values: Iterable[object] = DEFAULT_WAKE_PHRASES
    elif isinstance(phrases, str):
        values = phrases.split(",")
    elif isinstance(phrases, Iterable):
        values = phrases
    else:
        values = [phrases]

    result: list[str] = []
    for value in values:
        phrase = normalize_text(value)
        if phrase and phrase not in result:
            result.append(phrase)
    return result or list(DEFAULT_WAKE_PHRASES)


@dataclass(frozen=True)
class WakeWordMatch:
    phrase: str
    command: str
    text: str


def match_wake_word(text: object, phrases: object = None) -> WakeWordMatch | None:
    """Return a wake-word match and any trailing command text."""
    normalized = normalize_text(text)
    if not normalized:
        return None

    padded = f" {normalized} "
    for phrase in sorted(normalize_wake_phrases(phrases), key=len, reverse=True):
        needle = f" {phrase} "
        idx = padded.find(needle)
        if idx < 0:
            continue
        command_start = idx + len(needle)
        command = padded[command_start:].strip()
        return WakeWordMatch(phrase=phrase, command=command, text=normalized)
    return None


class WakeWordDetector:
    """Debounced wake-word detector for streaming partial/final transcripts."""

    def __init__(
        self,
        phrases: object = None,
        *,
        debounce_seconds: float = 1.5,
        partial_stability_seconds: float = 0.4,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.phrases = normalize_wake_phrases(phrases)
        self.debounce_seconds = max(0.0, float(debounce_seconds))
        self.partial_stability_seconds = max(0.0, float(partial_stability_seconds))
        self.clock = clock or time.monotonic
        self._last_triggered_at = -999999.0
        self._partial_text = ""
        self._partial_started_at = -999999.0

    def update_phrases(self, phrases: object) -> None:
        self.phrases = normalize_wake_phrases(phrases)
        self._partial_text = ""
        self._partial_started_at = -999999.0

    def detect(self, text: object, *, is_partial: bool = False) -> WakeWordMatch | None:
        match = match_wake_word(text, self.phrases)
        if match is None:
            if is_partial:
                self._partial_text = ""
            return None

        now = self.clock()
        if is_partial:
            # A bare wake phrase may still grow into "hey nova <command>".
            # Wait for Vosk's final result before opening follow-up capture.
            if not match.command:
                self._partial_text = match.text
                self._partial_started_at = now
                return None
            if match.text != self._partial_text:
                self._partial_text = match.text
                self._partial_started_at = now
                return None
            if now - self._partial_started_at < self.partial_stability_seconds:
                return None
        else:
            self._partial_text = ""

        if now - self._last_triggered_at < self.debounce_seconds:
            return None
        self._last_triggered_at = now
        self._partial_text = ""
        return match
