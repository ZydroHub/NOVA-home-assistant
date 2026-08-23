"""API tests using FastAPI TestClient. SKIP_MODEL_LOAD is set in conftest so models are not loaded."""
import os

import pytest
from starlette.websockets import WebSocketDisconnect

# Ensure SKIP_MODEL_LOAD is set before importing app (conftest sets it)
os.environ.setdefault("SKIP_MODEL_LOAD", "1")

def auth_headers():
    from app import NOVA_INTERNAL_CONTROL_TOKEN
    return {"X-NOVA-Token": NOVA_INTERNAL_CONTROL_TOKEN}


def test_health():
    """GET /health returns ok."""
    from fastapi.testclient import TestClient
    from app import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"


def test_conversations_list():
    """GET /conversations returns a list (may be empty)."""
    from fastapi.testclient import TestClient
    from app import app
    client = TestClient(app)
    resp = client.get("/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_conversations_create():
    """POST /conversations creates a conversation and returns it."""
    from fastapi.testclient import TestClient
    from app import app
    client = TestClient(app)
    resp = client.post("/conversations", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "title" in data
    assert data["title"] == "New Chat" or "title" in data


def test_alert_settings_api_get_and_post():
    """Alert settings can be read and patched for the GUI."""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    resp = client.get("/settings/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["alerts"]["nacka"] is True
    assert data["alerts"]["stockholm"] is True
    assert data["telegram"]["startup_notifications"] is True

    resp = client.post(
        "/settings/alerts",
        json={"alerts": {"stockholm": False}, "telegram": {"startup_notifications": False}},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["alerts"]["nacka"] is True
    assert data["alerts"]["stockholm"] is False
    assert data["telegram"]["startup_notifications"] is False


def test_control_endpoint_requires_valid_token():
    """State-changing control endpoints reject missing or invalid local GUI authorization."""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)
    resp = client.post("/settings/alerts", json={"alerts": {"stockholm": True}})
    assert resp.status_code == 401

    resp = client.post(
        "/settings/alerts",
        json={"alerts": {"stockholm": True}},
        headers={"X-NOVA-Token": "wrong"},
    )
    assert resp.status_code == 403


def test_control_token_endpoint_is_local_device_only():
    """Only the NOVA device may obtain the runtime authorization token."""
    from fastapi.testclient import TestClient
    from app import app

    remote_client = TestClient(app, client=("192.168.1.50", 50000))
    resp = remote_client.get("/system/control-token")
    assert resp.status_code == 403

    client = TestClient(app, client=("127.0.0.1", 50000))
    resp = client.get("/system/control-token")
    assert resp.status_code == 200
    from app import NOVA_INTERNAL_CONTROL_TOKEN

    assert resp.json()["token"] == NOVA_INTERNAL_CONTROL_TOKEN


def test_soul_status_endpoint_returns_debug_metadata_only():
    """Soul status exposes debug metadata without returning soul content."""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)
    resp = client.get("/system/soul-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] is True
    assert "memory_entry_count" in data
    assert "content" not in data
    assert "manual_section" not in data


def test_local_control_requests_work_without_bootstrap_token():
    """The kiosk can still use controls if browser token bootstrapping fails."""
    from fastapi.testclient import TestClient
    from app import _is_local_client, app

    assert _is_local_client("::ffff:127.0.0.1") is True

    client = TestClient(app, client=("127.0.0.1", 50000))
    resp = client.post("/settings/alerts", json={"alerts": {"stockholm": True}})
    assert resp.status_code == 200

    stale_token = client.post(
        "/settings/alerts",
        json={"alerts": {"stockholm": True}},
        headers={"X-NOVA-Token": "stale-token-after-restart"},
    )
    assert stale_token.status_code == 200


def test_websocket_endpoints_allow_local_bootstrap_fallback_and_reject_remote_clients():
    """Local kiosk sockets keep working if token bootstrap fails; remote sockets still need auth."""
    from fastapi.testclient import TestClient
    from app import NOVA_INTERNAL_CONTROL_TOKEN, app

    local_client = TestClient(app, client=("127.0.0.1", 50000))
    remote_client = TestClient(app, client=("192.168.1.50", 50000))
    conversation = local_client.post("/conversations").json()

    with pytest.raises(WebSocketDisconnect) as rejected_remote:
        with remote_client.websocket_connect("/ws/system-stats"):
            pass
    assert rejected_remote.value.code == 1008

    with local_client.websocket_connect("/ws/system-stats") as websocket:
        payload = websocket.receive_json()
    assert "cpu_percent" in payload

    with local_client.websocket_connect(f"/ws/system-stats?token={NOVA_INTERNAL_CONTROL_TOKEN}") as websocket:
        payload = websocket.receive_json()
    assert "cpu_percent" in payload

    with local_client.websocket_connect(f"/ws/chat/{conversation['id']}") as websocket:
        history = websocket.receive_json()
    assert history["type"] == "history"

    with local_client.websocket_connect(
        f"/ws/chat/{conversation['id']}?token={NOVA_INTERNAL_CONTROL_TOKEN}"
    ) as websocket:
        history = websocket.receive_json()
    assert history["type"] == "history"

    with pytest.raises(WebSocketDisconnect) as rejected_remote_voice:
        with remote_client.websocket_connect("/ws/voice"):
            pass
    assert rejected_remote_voice.value.code == 1008

    with local_client.websocket_connect("/ws/voice"):
        pass

    with local_client.websocket_connect(f"/ws/voice?token={NOVA_INTERNAL_CONTROL_TOKEN}"):
        pass

    with local_client.websocket_connect("/ws/voice?token=stale-token-after-restart"):
        pass


def test_voice_settings_api_get_and_post():
    """Voice speech-to-text language can be read and patched for the GUI."""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    resp = client.get("/settings/voice")
    assert resp.status_code == 200
    data = resp.json()
    assert data["voice"]["language"] == "en"
    assert data["voice"]["always_listening"] is True
    assert data["voice"]["wake_phrases"] == [
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
    ]
    assert data["voice"]["wake_command_mode"] == "direct_or_listen"
    assert any(language["value"] == "en" for language in data["languages"])

    resp = client.post(
        "/settings/voice",
        json={"language": "sv", "always_listening": True, "wake_phrases": "hey nova, hej nova"},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["voice"]["language"] == "sv"
    assert data["voice"]["always_listening"] is True
    assert data["voice"]["wake_phrases"][:2] == ["hey nova", "hej nova"]
    assert "nova" in data["voice"]["wake_phrases"]
    assert "hey noah" in data["voice"]["wake_phrases"]
    assert data["runtime"]["language"] == "sv"
    assert data["runtime"]["always_listening"] is True

    resp = client.post("/settings/voice", json={"language": "klingon"}, headers=auth_headers())
    assert resp.status_code == 400

    resp = client.post("/settings/voice", json={"wake_command_mode": "unsupported"}, headers=auth_headers())
    assert resp.status_code == 400


def test_model_settings_api_get_and_rejects_invalid_or_remote_changes():
    """Model selection is readable locally but state changes remain protected."""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)
    response = client.get("/settings/models")
    assert response.status_code == 200
    data = response.json()
    assert data["selected_model"] == "qwen3-0.6b"
    assert {item["id"] for item in data["options"]} == {
        "qwen3-0.6b",
        "llama3.2-1b",
        "qwen2.5-1.5b",
        "llama3.2-3b",
    }

    invalid = client.post("/settings/models", json={"model": "not-a-model"}, headers=auth_headers())
    assert invalid.status_code == 400

    remote_client = TestClient(app, client=("192.168.1.50", 50000))
    rejected = remote_client.post("/settings/models", json={"model": "llama3.2-1b"})
    assert rejected.status_code == 401


def test_spotify_device_selection_prefers_requested_device():
    """Spotify controls should target the dashboard-selected device when provided."""
    from fastapi import HTTPException
    from app import _select_spotify_device

    devices_payload = {
        "devices": [
            {"id": "local", "name": "raspotify"},
            {"id": "phone", "name": "Phone"},
        ]
    }

    assert _select_spotify_device(devices_payload, "phone")["id"] == "phone"
    assert _select_spotify_device(devices_payload)["id"] == "local"

    with pytest.raises(HTTPException) as exc_info:
        _select_spotify_device(devices_payload, "missing")
    assert exc_info.value.status_code == 404


def test_spotify_play_resumes_paused_music_without_toggling(monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_module

    class FakeSpotify:
        def __init__(self):
            self.is_playing = False
            self.start_calls = []

        def devices(self):
            return {"devices": [{"id": "speaker", "name": "NOVA", "is_active": True}]}

        def current_playback(self):
            return {
                "is_playing": self.is_playing,
                "item": {
                    "name": "Midnight City",
                    "artists": [{"name": "M83"}],
                    "album": {"images": []},
                    "duration_ms": 240000,
                },
            }

        def start_playback(self, device_id=None):
            self.start_calls.append(device_id)
            self.is_playing = True

    fake = FakeSpotify()
    monkeypatch.setattr(app_module, "_spotify_client", lambda: fake)
    client = TestClient(app_module.app)

    response = client.post("/nova/spotify/play", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["title"] == "Midnight City"
    assert response.json()["artist"] == "M83"
    assert response.json()["is_playing"] is True
    assert fake.start_calls == ["speaker"]

    response = client.post("/nova/spotify/play", headers=auth_headers())

    assert response.status_code == 200
    assert fake.start_calls == ["speaker"]


def test_spotify_duck_restores_original_volume(monkeypatch):
    """Spotify ducking stores the current volume and restores it after voice activity."""
    import app as app_module

    class FakeSpotify:
        def __init__(self):
            self.volume_calls = []

        def devices(self):
            return {
                "devices": [
                    {
                        "id": "speaker",
                        "name": "Kitchen speaker",
                        "volume_percent": 68,
                        "is_active": True,
                    }
                ]
            }

        def volume(self, volume_percent, device_id=None):
            self.volume_calls.append((volume_percent, device_id))

    fake = FakeSpotify()
    monkeypatch.setattr(app_module, "_spotify_client", lambda: fake)
    with app_module._SPOTIFY_DUCK_LOCK:
        app_module._SPOTIFY_DUCK_STATE.update({"active": False, "device_id": None, "volume_percent": None})

    ducked = app_module._spotify_duck_blocking(volume_percent=15)
    restored = app_module._spotify_duck_blocking(restore=True)

    assert ducked["active"] is True
    assert ducked["restore_volume_percent"] == 68
    assert restored["active"] is False
    assert restored["restored"] is True
    assert fake.volume_calls == [(15, "speaker"), (68, "speaker")]


def test_spotify_duck_skips_when_no_active_device(monkeypatch):
    """Voice ducking stays quiet when Spotify has no active playback device."""
    import app as app_module

    class FakeSpotify:
        def __init__(self):
            self.volume_calls = []

        def devices(self):
            return {"devices": [{"id": "speaker", "name": "NOVA", "is_active": False, "volume_percent": 68}]}

        def volume(self, volume_percent, device_id=None):
            self.volume_calls.append((volume_percent, device_id))

    fake = FakeSpotify()
    monkeypatch.setattr(app_module, "_spotify_client", lambda: fake)
    with app_module._SPOTIFY_DUCK_LOCK:
        app_module._SPOTIFY_DUCK_STATE.update({"active": False, "device_id": None, "volume_percent": None})

    result = app_module._spotify_duck_blocking(volume_percent=15)

    assert result == {
        "status": "skipped",
        "active": False,
        "reason": "no_active_device",
        "device_id": None,
        "device_name": None,
    }
    assert fake.volume_calls == []


def test_spotify_duck_does_not_mark_state_active_when_player_disappears(monkeypatch):
    """A Spotify race during ducking leaves no stale volume restore state."""
    import app as app_module

    class FakeSpotifyError(Exception):
        http_status = 404

        def __str__(self):
            return "Player command failed: No active device found"

    class FakeSpotify:
        def devices(self):
            return {"devices": [{"id": "speaker", "name": "NOVA", "is_active": True, "volume_percent": 68}]}

        def volume(self, _volume_percent, device_id=None):
            raise FakeSpotifyError()

    monkeypatch.setattr(app_module, "_spotify_client", lambda: FakeSpotify())
    with app_module._SPOTIFY_DUCK_LOCK:
        app_module._SPOTIFY_DUCK_STATE.update({"active": False, "device_id": None, "volume_percent": None})

    result = app_module._spotify_duck_blocking(volume_percent=15)

    assert result["status"] == "skipped"
    assert result["reason"] == "no_active_device"
    assert app_module._SPOTIFY_DUCK_STATE == {"active": False, "device_id": None, "volume_percent": None}
