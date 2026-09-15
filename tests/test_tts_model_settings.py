"""Tests for selectable Piper voice qualities."""

import chat_ai
from tts_model_settings import DEFAULT_TTS_VOICE_ID, TTS_VOICES, TtsVoiceSettingsStore


def test_tts_voice_registry_has_three_quality_levels():
    assert [(voice.id, voice.model_name) for voice in TTS_VOICES] == [
        ("low", "en_US-lessac-low"),
        ("medium", "en_US-lessac-medium"),
        ("high", "en_US-lessac-high"),
    ]


def test_tts_voice_settings_defaults_and_persists_selection(tmp_path):
    path = tmp_path / "tts_settings.json"
    store = TtsVoiceSettingsStore(path)
    assert store.get_selected_voice() == DEFAULT_TTS_VOICE_ID

    store.set_selected_voice("medium")
    reloaded = TtsVoiceSettingsStore(path)
    assert reloaded.get_selected_voice() == "medium"


def test_failed_tts_voice_switch_keeps_previous_engine(monkeypatch):
    state = chat_ai.AIState()
    previous_tts = object()
    state.tts = previous_tts
    state._active_tts_voice_id = "high"

    def fail_to_load(_model_name):
        raise RuntimeError("download failed")

    monkeypatch.setattr(chat_ai, "PocketAudio", fail_to_load)
    state._tts_switching = True
    state._switch_tts_voice_worker("medium")

    status = state.get_tts_runtime_status()
    assert state.tts is previous_tts
    assert status["active_voice"] == "high"
    assert status["switching"] is False
    assert "download failed" in status["error"]
