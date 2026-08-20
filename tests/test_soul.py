import os
import threading
import time

import pytest

import chat_ai
import soul
from soul import SoulStore


def soul_content(identity: str = "NOVA is steady.", memory: str = "") -> str:
    return f"""# NOVA Soul

## Core Identity

{identity}

## Behavioral Rules

- Be concise.

## Auto Memory

{memory}"""


def test_missing_soul_bootstraps_local_file(tmp_path):
    store = SoulStore(tmp_path / "missing.md")

    snapshot = store.get()

    assert snapshot.file_present is True
    assert snapshot.parse_error is None
    assert snapshot.path.exists()
    assert "NOVA Soul" in snapshot.content


def test_valid_soul_is_parsed(tmp_path):
    path = tmp_path / "soul.md"
    path.write_text(soul_content(memory="- 2026-01-01T00:00:00Z - The user likes quiet replies.\n"), encoding="utf-8")
    store = SoulStore(path)

    snapshot = store.get()

    assert snapshot.file_present is True
    assert "NOVA is steady." in snapshot.manual_section
    assert snapshot.memory_entries == ("- 2026-01-01T00:00:00Z - The user likes quiet replies.",)


def test_invalid_soul_keeps_last_valid_snapshot(tmp_path):
    path = tmp_path / "soul.md"
    path.write_text(soul_content(identity="Original soul."), encoding="utf-8")
    store = SoulStore(path)
    assert "Original soul." in store.get().manual_section

    time.sleep(0.001)
    path.write_text("# Broken\n\nNo memory header.", encoding="utf-8")
    os.utime(path, None)
    snapshot = store.get()

    assert "Original soul." in snapshot.manual_section
    assert snapshot.parse_error


def test_soul_auto_reloads_when_file_changes(tmp_path):
    path = tmp_path / "soul.md"
    path.write_text(soul_content(identity="First soul."), encoding="utf-8")
    store = SoulStore(path)
    assert "First soul." in store.get().manual_section

    time.sleep(0.001)
    path.write_text(soul_content(identity="Second soul."), encoding="utf-8")
    os.utime(path, None)

    assert "Second soul." in store.get().manual_section


def test_append_memory_only_changes_auto_memory_section(tmp_path):
    path = tmp_path / "soul.md"
    path.write_text(soul_content(identity="Protected manual soul."), encoding="utf-8")
    store = SoulStore(path)

    result = store.append_memories(["The user prefers concise answers."])
    content = path.read_text(encoding="utf-8")
    manual, memory = content.split(soul.AUTO_MEMORY_HEADER, 1)

    assert result.added is True
    assert "Protected manual soul." in manual
    assert "The user prefers concise answers." in memory


def test_duplicate_memory_candidates_are_skipped(tmp_path):
    path = tmp_path / "soul.md"
    path.write_text(soul_content(), encoding="utf-8")
    store = SoulStore(path)

    first = store.append_memories(["The user likes compact music controls."])
    second = store.append_memories(["The user likes compact music controls."])

    assert first.added is True
    assert second.added is False
    assert second.reason == "duplicate"
    assert len(store.get().memory_entries) == 1


def test_memory_entries_are_trimmed(monkeypatch, tmp_path):
    monkeypatch.setattr(soul, "MAX_MEMORY_ENTRIES", 2)
    path = tmp_path / "soul.md"
    path.write_text(soul_content(), encoding="utf-8")
    store = SoulStore(path)

    store.append_memories(["Memory one.", "Memory two.", "Memory three."])

    entries = store.get().memory_entries
    assert len(entries) == 2
    assert "Memory one." not in "\n".join(entries)
    assert "Memory three." in entries[-1]


def test_concurrent_memory_writes_do_not_corrupt_file(tmp_path):
    path = tmp_path / "soul.md"
    path.write_text(soul_content(), encoding="utf-8")
    store = SoulStore(path)

    threads = [
        threading.Thread(target=store.append_memories, args=([f"The user likes stable fact {index}."],))
        for index in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    snapshot = store.get()
    assert snapshot.parse_error is None
    assert len(snapshot.memory_entries) == 8


def test_heuristics_capture_stable_preferences_not_transient_or_sensitive():
    assert soul.derive_memory_candidates("I prefer short answers.") == ("The user prefers short answers.",)
    assert soul.derive_memory_candidates("My API key is abc123.") == ()
    assert soul.derive_memory_candidates("I like this song today.") == ()


def test_chat_and_voice_prompt_builders_use_soul(monkeypatch):
    state = chat_ai.AIState()
    monkeypatch.setattr(chat_ai, "build_soul_system_prompt", lambda mode="chat": f"SOUL-{mode}")

    chat_messages = state._build_llm_messages([{"role": "user", "content": "hello"}])
    state.voice_messages = [{"role": "system", "content": "old"}]
    state._refresh_voice_system_message()

    assert chat_messages[0] == {"role": "system", "content": "SOUL-chat"}
    assert state.voice_messages[0] == {"role": "system", "content": "SOUL-voice"}
