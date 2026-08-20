"""Tests for ConversationManager (no FastAPI, no LLM)."""
import json
import os

import pytest

from chat_ai import ConversationManager


def test_conversation_manager_create_list_delete(temp_storage_path):
    """ConversationManager CRUD with a temp file."""
    cm = ConversationManager(temp_storage_path)
    assert cm.list_conversations() == []

    c1 = cm.create_conversation("First")
    assert c1["title"] == "First"
    assert "id" in c1
    assert c1["messages"] == []

    c2 = cm.create_conversation("Second", messages=[{"role": "user", "content": "Hi"}])
    assert c2["messages"]

    listed = cm.list_conversations()
    assert len(listed) == 2
    ids = {x["id"] for x in listed}
    assert c1["id"] in ids and c2["id"] in ids

    cm.delete_conversation(c1["id"])
    assert len(cm.list_conversations()) == 1
    assert cm.get_conversation(c1["id"]) is None
    assert cm.get_conversation(c2["id"]) is not None


def test_conversation_manager_rename(temp_storage_path):
    """ConversationManager rename_conversation."""
    cm = ConversationManager(temp_storage_path)
    c = cm.create_conversation("Original")
    out = cm.rename_conversation(c["id"], "Renamed")
    assert out is not None
    assert out["title"] == "Renamed"
    assert cm.get_conversation(c["id"])["title"] == "Renamed"


def test_conversation_manager_persists(temp_storage_path):
    """Conversations persist across manager instances."""
    cm1 = ConversationManager(temp_storage_path)
    c = cm1.create_conversation("Saved")
    conv_id = c["id"]
    cm1.flush_conversations()
    del cm1

    cm2 = ConversationManager(temp_storage_path)
    loaded = cm2.get_conversation(conv_id)
    assert loaded is not None
    assert loaded["title"] == "Saved"
