"""Tests for selectable local chat models."""

import chat_ai
from model_settings import CHAT_MODELS, ChatModelSettingsStore, DEFAULT_CHAT_MODEL_ID


def test_model_registry_has_expected_models_and_filenames():
    expected = {
        "qwen3-0.6b": "Qwen3-0.6B-Q8_0.gguf",
        "llama3.2-1b": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "qwen2.5-1.5b": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "llama3.2-3b": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    }
    assert {model.id: model.filename for model in CHAT_MODELS} == expected


def test_model_settings_defaults_and_persists_selection(tmp_path):
    path = tmp_path / "model_settings.json"
    store = ChatModelSettingsStore(path)
    assert store.get_selected_model() == DEFAULT_CHAT_MODEL_ID

    store.set_selected_model("llama3.2-1b")
    reloaded = ChatModelSettingsStore(path)
    assert reloaded.get_selected_model() == "llama3.2-1b"


def test_failed_runtime_switch_keeps_previous_model(monkeypatch):
    state = chat_ai.AIState()
    previous_model = object()
    state.llm = previous_model
    state._active_model_id = DEFAULT_CHAT_MODEL_ID

    def fail_to_load(_model_id):
        raise RuntimeError("download failed")

    monkeypatch.setattr(state, "_load_chat_model", fail_to_load)
    state._model_switching = True
    state._switch_chat_model_worker("llama3.2-1b")

    status = state.get_model_runtime_status()
    assert state.llm is previous_model
    assert status["active_model"] == DEFAULT_CHAT_MODEL_ID
    assert status["switching"] is False
    assert "download failed" in status["error"]


def test_startup_uses_available_default_while_selected_model_downloads(monkeypatch):
    class FakePath:
        def __init__(self, available):
            self.available = available

        def exists(self):
            return self.available

    class FakeSpec:
        def __init__(self, label, available):
            self.label = label
            self.path = FakePath(available)

    state = chat_ai.AIState()
    selected_model = "llama3.2-1b"
    loaded_models = []
    switch_requests = []
    specs = {
        selected_model: FakeSpec("Llama 3.2 1B", False),
        DEFAULT_CHAT_MODEL_ID: FakeSpec("Qwen3 0.6B", True),
    }

    monkeypatch.setattr(chat_ai.get_chat_model_settings_store(), "get_selected_model", lambda: selected_model)
    monkeypatch.setattr(chat_ai, "get_chat_model_spec", specs.__getitem__)
    monkeypatch.setattr(state, "_load_chat_model", loaded_models.append)
    monkeypatch.setattr(state, "_load_speech_models", lambda: None)
    monkeypatch.setattr(state, "request_model_switch", switch_requests.append)

    state.load_model()

    assert loaded_models == [DEFAULT_CHAT_MODEL_ID]
    assert switch_requests == [selected_model]
