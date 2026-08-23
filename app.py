import os
os.environ["LONG_LOG_LEVEL"] = "3"
os.environ["ORT_LOGGING_LEVEL"] = "3"
os.environ.setdefault("ORT_LOG_SEVERITY_LEVEL", "3")
os.environ.setdefault("VOSK_LOG_LEVEL", "0")
os.environ.setdefault("KALDI_LOG_LEVEL", "0")

import logging
import math
import json
import asyncio
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import threading
import html
import ipaddress
import socket
from contextlib import asynccontextmanager
from asyncio import sleep
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psutil
import requests
import uvicorn
from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from alert_settings import ALERT_REGIONS, get_alert_settings_store
from config import (
    NOVA_BIND_HOST,
    NOVA_INTERNAL_CONTROL_TOKEN,
    NOVA_AUDIO_RELEASE_COMMANDS,
    PORT,
    is_valid_control_token,
    setup_logging,
)
from news_alerts import fetch_swedish_alerts
from model_settings import get_chat_model_options, get_chat_model_settings_store, get_chat_model_spec
from soul import get_soul_status
from telegram_bot import get_telegram_bot, start_telegram_bot, stop_telegram_bot
from quiet_io import silence_stderr_fd
from weather import get_weather

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _nova_project_root() -> Path:
    return Path(os.getenv("NOVA_PROJECT_ROOT", Path(__file__).resolve().parent)).resolve()


def _nova_env_path() -> Path:
    return Path(os.getenv("NOVA_ENV_PATH", _nova_project_root() / ".env"))


def _nova_env_candidates() -> list[Path]:
    candidates = [
        _nova_env_path(),
        _nova_project_root() / ".env",
        Path(__file__).resolve().parent / ".env",
    ]
    unique_candidates: list[Path] = []
    for candidate in candidates:
        if candidate not in unique_candidates:
            unique_candidates.append(candidate)
    return unique_candidates


def _load_environment_file() -> None:
    if load_dotenv is None:
        return
    for dotenv_path in _nova_env_candidates():
        if dotenv_path.exists():
            load_dotenv(dotenv_path=dotenv_path, override=False)
            return
    load_dotenv(dotenv_path=_nova_env_path(), override=False)


def _dependency_error(package_hint: str, exc: Exception) -> RuntimeError:
    return RuntimeError(
        f"Missing or incompatible dependency while importing {package_hint}: {exc}. "
        "Install dependencies explicitly before startup with: "
        f"{sys.executable} -m pip install -r requirements.txt"
    )


def _import_fastapi_components():
    try:
        from fastapi import FastAPI as _FastAPI
        from fastapi import WebSocket as _WebSocket
        from fastapi import WebSocketDisconnect as _WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware as _CORSMiddleware
        return _FastAPI, _CORSMiddleware, _WebSocket, _WebSocketDisconnect
    except Exception as exc:
        raise _dependency_error("FastAPI", exc) from exc


def _import_chat_state():
    try:
        with silence_stderr_fd():
            from chat_ai import router as _chat_router, ai as _ai_state
        return _chat_router, _ai_state
    except Exception as exc:
        raise _dependency_error("chat/LLM stack", exc) from exc


def _import_spotify():
    try:
        import spotipy as _spotipy
        from spotipy.oauth2 import SpotifyOAuth as _SpotifyOAuth
        return _spotipy, _SpotifyOAuth
    except Exception as exc:
        raise _dependency_error("Spotify integration", exc) from exc


FastAPI, CORSMiddleware, WebSocket, WebSocketDisconnect = _import_fastapi_components()
chat_router, ai_state = _import_chat_state()
spotipy, SpotifyOAuth = _import_spotify()

_load_environment_file()

setup_logging()
logger = logging.getLogger(__name__)

_startup_lock = threading.Lock()
_startup_completed = False

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"
SPOTIFY_SCOPES = "user-read-currently-playing user-modify-playback-state user-read-playback-state playlist-read-private"
SPOTIFY_CACHE_PATH = ".spotify_cache"
SPOTIFY_DASHBOARD_REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"
AUDIO_SOURCE_STATE = (os.getenv("NOVA_AUDIO_SOURCE", "spotify") or "spotify").strip().lower()
_PLAYLISTS_CACHE = {"data": [], "last_fetched": datetime.min}
_PLAYLISTS_CACHE_LOCK = threading.Lock()
_SYSTEM_STATS_CACHE = {"data": None, "last_fetched": datetime.min}
_SYSTEM_STATS_CACHE_LOCK = threading.Lock()
_SPOTIFY_AUDIO_STATE_CACHE = {"data": None, "last_fetched": datetime.min}
_SPOTIFY_AUDIO_STATE_CACHE_LOCK = threading.Lock()
_SPOTIFY_DUCK_LOCK = threading.Lock()
_SPOTIFY_DUCK_STATE = {"active": False, "device_id": None, "volume_percent": None}


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return ""
    return token.strip()


def require_control_auth(
    request: Request,
    x_nova_token: str | None = Header(default=None, alias="X-NOVA-Token"),
    authorization: str | None = Header(default=None),
) -> None:
    """Require the current local GUI token for state-changing endpoints."""
    expected = (NOVA_INTERNAL_CONTROL_TOKEN or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Local GUI authorization is unavailable; control endpoints are disabled.",
        )

    client_host = request.client.host if request.client else None
    if _is_local_client(client_host):
        return
    provided = (x_nova_token or "").strip() or _bearer_token(authorization)
    if not provided:
        raise HTTPException(
            status_code=401,
            detail="Missing local GUI authorization.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not is_valid_control_token(provided):
        raise HTTPException(status_code=403, detail="Invalid local GUI authorization.")


CONTROL_AUTH = [Depends(require_control_auth)]


def _normalized_ip_address(host: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not host:
        return None
    if host.lower() == "localhost":
        return ipaddress.ip_address("127.0.0.1")
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            return address.ipv4_mapped
        return address
    except ValueError:
        return None


def _is_local_client(host: str | None) -> bool:
    address = _normalized_ip_address(host)
    if address is None:
        return False
    if address.is_loopback:
        return True

    try:
        local_addresses = {
            _normalized_ip_address(info[4][0])
            for info in socket.getaddrinfo(socket.gethostname(), None)
            if info[4]
        }
    except OSError:
        local_addresses = set()
    return address in local_addresses


def require_local_control_token_request(request: Request) -> None:
    """Only the NOVA device itself may retrieve the runtime GUI token."""
    client_host = request.client.host if request.client else None
    if not _is_local_client(client_host):
        raise HTTPException(status_code=403, detail="Control token is available only to the local NOVA device.")


async def authorize_control_websocket(websocket: WebSocket) -> bool:
    """Reject unauthenticated WebSocket clients before accepting the socket."""
    token = websocket.query_params.get("token")
    client_host = websocket.client.host if websocket.client else None
    if _is_local_client(client_host) or is_valid_control_token(token):
        return True
    await websocket.close(code=1008, reason="Missing or invalid local GUI authorization")
    return False


def _invalidate_spotify_audio_state_cache() -> None:
    with _SPOTIFY_AUDIO_STATE_CACHE_LOCK:
        _SPOTIFY_AUDIO_STATE_CACHE["data"] = None
        _SPOTIFY_AUDIO_STATE_CACHE["last_fetched"] = datetime.min


if not os.getenv("SPOTIFY_CLIENT_ID") or not os.getenv("SPOTIFY_CLIENT_SECRET"):
    logger.warning(
        "Spotify credentials are missing. Check %s for SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.",
        _nova_env_path(),
    )


def _spotify_configured() -> bool:
    return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)


def _render_status_page(title: str, summary: str, details: list[str], status_code: int = 200) -> HTMLResponse:
    safe_title = html.escape(title)
    safe_summary = html.escape(summary)
    detail_items = "".join(f"<li>{html.escape(item)}</li>" for item in details)
    env_items = "".join(
        f"<li>{html.escape(str(candidate))}: {'yes' if candidate.exists() else 'no'}</li>"
        for candidate in _nova_env_candidates()
    )
    html = f"""
    <html>
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>{safe_title}</title>
        </head>
        <body style="font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0b1022;color:#e4f7ff;padding:24px;line-height:1.55;">
            <div style="max-width:840px;margin:0 auto;">
                <h1 style="margin:0 0 12px 0;font-size:2rem;">{safe_title}</h1>
                <p style="font-size:1.05rem;margin:0 0 20px 0;">{safe_summary}</p>
                <div style="padding:16px 18px;border:1px solid rgba(132,211,255,0.25);border-radius:16px;background:rgba(255,255,255,0.04);margin-bottom:18px;">
                    <strong>What to check</strong>
                    <ul style="margin:12px 0 0 20px;">
                        {detail_items}
                    </ul>
                </div>
                <div style="padding:16px 18px;border:1px solid rgba(132,211,255,0.18);border-radius:16px;background:rgba(255,255,255,0.03);">
                    <strong>Current backend info</strong>
                    <ul style="margin:12px 0 0 20px;">
                        <li>Backend URL: http://127.0.0.1:{PORT}</li>
                        <li>Spotify redirect URI: {html.escape(SPOTIFY_REDIRECT_URI)}</li>
                        <li>Env search path: NOVA_ENV_PATH, NOVA_PROJECT_ROOT/.env, local .env</li>
                        {env_items}
                        <li>SPOTIFY_CLIENT_ID loaded: {"yes" if bool(SPOTIFY_CLIENT_ID) else "no"}</li>
                        <li>SPOTIFY_CLIENT_SECRET loaded: {"yes" if bool(SPOTIFY_CLIENT_SECRET) else "no"}</li>
                        <li>Spotify configured: {"yes" if _spotify_configured() else "no"}</li>
                    </ul>
                </div>
            </div>
        </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=status_code)


def _spotify_oauth() -> Any:
    if not _spotify_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Spotify is not configured. Check that NOVA_PROJECT_ROOT/.env or NOVA_ENV_PATH contains "
                "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET. Also verify the Spotify redirect URI is "
                f"{SPOTIFY_DASHBOARD_REDIRECT_URI}."
            ),
        )
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPES,
        cache_path=SPOTIFY_CACHE_PATH,
        open_browser=False,
    )


def _spotify_client() -> Any:
    return spotipy.Spotify(auth_manager=_spotify_oauth())


def _spotify_track_payload(playback: object) -> dict:
    if not isinstance(playback, dict):
        return {
            "title": "",
            "artist": "",
            "album_art_url": "",
            "progress_ms": 0,
            "duration_ms": 0,
            "is_playing": False,
            "shuffle_state": False,
        }

    item = playback.get("item") if isinstance(playback.get("item"), dict) else {}
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    images = album.get("images") if isinstance(album.get("images"), list) else []
    artists = item.get("artists") if isinstance(item.get("artists"), list) else []
    artist_names = ", ".join(
        artist.get("name")
        for artist in artists
        if isinstance(artist, dict) and artist.get("name")
    )

    return {
        "title": str(item.get("name") or ""),
        "artist": artist_names,
        "album_art_url": str(images[0].get("url") if images and isinstance(images[0], dict) and images[0].get("url") else ""),
        "progress_ms": int(playback.get("progress_ms") or 0),
        "duration_ms": int(item.get("duration_ms") or 0),
        "is_playing": bool(playback.get("is_playing")),
        "shuffle_state": bool(playback.get("shuffle_state")),
    }


def _spotify_playlist_payload(playlist: object) -> dict:
    if not isinstance(playlist, dict):
        return {"id": "", "name": "", "image_url": ""}

    images = playlist.get("images") if isinstance(playlist.get("images"), list) else []
    first_image = images[0] if images and isinstance(images[0], dict) else {}
    return {
        "id": str(playlist.get("id") or ""),
        "name": str(playlist.get("name") or ""),
        "image_url": str(first_image.get("url") or ""),
    }


def _spotify_queue_track_payload(track: object) -> dict:
    if not isinstance(track, dict):
        return {"id": "", "title": "", "artist": "", "album_art_url": ""}

    album = track.get("album") if isinstance(track.get("album"), dict) else {}
    images = album.get("images") if isinstance(album.get("images"), list) else []
    artists = track.get("artists") if isinstance(track.get("artists"), list) else []
    return {
        "id": str(track.get("id") or track.get("uri") or ""),
        "title": str(track.get("name") or ""),
        "artist": ", ".join(
            str(artist.get("name"))
            for artist in artists
            if isinstance(artist, dict) and artist.get("name")
        ),
        "album_art_url": str(
            images[0].get("url")
            if images and isinstance(images[0], dict) and images[0].get("url")
            else ""
        ),
    }


def _pick_spotify_device(devices_payload: object) -> dict | None:
    devices = devices_payload.get("devices") if isinstance(devices_payload, dict) else None
    if not isinstance(devices, list) or not devices:
        return None

    preferred_names = ("raspotify", "raspberrypi")

    for device in devices:
        if not isinstance(device, dict):
            continue
        name = str(device.get("name") or "").lower()
        if any(preferred in name for preferred in preferred_names):
            return device

    active_devices = [device for device in devices if isinstance(device, dict) and device.get("is_active")]
    if active_devices:
        return active_devices[0]

    return devices[0] if isinstance(devices[0], dict) else None


def _select_spotify_device(devices_payload: object, requested_device_id: str | None = None) -> dict | None:
    devices = devices_payload.get("devices") if isinstance(devices_payload, dict) else None
    if not isinstance(devices, list) or not devices:
        return None

    requested_id = str(requested_device_id or "").strip()
    if requested_id:
        for device in devices:
            if isinstance(device, dict) and str(device.get("id") or "") == requested_id:
                return device
        raise HTTPException(status_code=404, detail="Spotify device not found.")

    return _pick_spotify_device(devices_payload)


def _pick_active_spotify_device(devices_payload: object, requested_device_id: str | None = None) -> dict | None:
    """Return a currently active player suitable for automatic voice ducking."""
    devices = devices_payload.get("devices") if isinstance(devices_payload, dict) else None
    if not isinstance(devices, list):
        return None

    requested_id = str(requested_device_id or "").strip()
    active_devices = [
        device
        for device in devices
        if isinstance(device, dict) and bool(device.get("is_active"))
    ]
    if requested_id:
        return next(
            (device for device in active_devices if str(device.get("id") or "") == requested_id),
            None,
        )

    preferred_names = ("raspotify", "raspberrypi")
    return next(
        (
            device
            for device in active_devices
            if any(preferred in str(device.get("name") or "").lower() for preferred in preferred_names)
        ),
        active_devices[0] if active_devices else None,
    )


def _spotify_duck_skipped(reason: str, *, device: dict | None = None) -> dict:
    return {
        "status": "skipped",
        "active": False,
        "reason": reason,
        "device_id": device.get("id") if isinstance(device, dict) else None,
        "device_name": device.get("name") if isinstance(device, dict) else None,
    }


def _is_no_active_spotify_device_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return getattr(exc, "http_status", None) == 404 and (
        "no_active_device" in message or "no active device" in message
    )


def _clamp_spotify_volume_percent(value: object, default: int = 20) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(0, min(100, number))


def _spotify_duck_blocking(
    restore: bool = False,
    volume_percent: int | None = None,
    device_id: str | None = None,
) -> dict:
    target_volume = _clamp_spotify_volume_percent(
        volume_percent,
        _clamp_spotify_volume_percent(os.getenv("NOVA_SPOTIFY_DUCK_VOLUME_PERCENT"), 20),
    )

    client = _spotify_client()

    with _SPOTIFY_DUCK_LOCK:
        if restore:
            stored_device_id = _SPOTIFY_DUCK_STATE.get("device_id")
            stored_volume = _SPOTIFY_DUCK_STATE.get("volume_percent")
            was_active = bool(_SPOTIFY_DUCK_STATE.get("active"))
            if not was_active or stored_volume is None:
                _SPOTIFY_DUCK_STATE.update({"active": False, "device_id": None, "volume_percent": None})
                return _spotify_duck_skipped("not_ducked")

            try:
                client.volume(_clamp_spotify_volume_percent(stored_volume), device_id=stored_device_id)
            except Exception as exc:
                if _is_no_active_spotify_device_error(exc):
                    logger.info("Spotify duck restore skipped because no player is active")
                    _SPOTIFY_DUCK_STATE.update({"active": False, "device_id": None, "volume_percent": None})
                    return _spotify_duck_skipped("no_active_device")
                raise

            _SPOTIFY_DUCK_STATE.update({"active": False, "device_id": None, "volume_percent": None})
            _invalidate_spotify_audio_state_cache()
            return {
                "status": "ok",
                "active": False,
                "device_id": stored_device_id,
                "device_name": None,
                "volume_percent": stored_volume,
                "restored": True,
            }

        devices_payload = client.devices()
        chosen = _pick_active_spotify_device(devices_payload, device_id)
        if chosen is None:
            logger.info("Spotify duck skipped because no player is active")
            return _spotify_duck_skipped("no_active_device")

        if chosen.get("supports_volume") is False or chosen.get("volume_percent") is None:
            logger.info("Spotify duck skipped because %s does not expose a restorable volume", chosen.get("name"))
            return _spotify_duck_skipped("volume_unavailable", device=chosen)

        chosen_id = str(chosen.get("id") or "") or None
        current_volume = _clamp_spotify_volume_percent(chosen.get("volume_percent"), 0)
        try:
            client.volume(target_volume, device_id=chosen_id)
        except Exception as exc:
            if _is_no_active_spotify_device_error(exc):
                logger.info("Spotify duck skipped because the player became inactive")
                return _spotify_duck_skipped("no_active_device", device=chosen)
            raise

        if not _SPOTIFY_DUCK_STATE.get("active"):
            _SPOTIFY_DUCK_STATE.update(
                {
                    "active": True,
                    "device_id": chosen_id,
                    "volume_percent": current_volume,
                }
            )
        _invalidate_spotify_audio_state_cache()
        return {
            "status": "ok",
            "active": True,
            "device_id": chosen_id,
            "device_name": chosen.get("name"),
            "volume_percent": target_volume,
            "restore_volume_percent": _SPOTIFY_DUCK_STATE.get("volume_percent"),
        }


def _device_payload(device: object) -> dict:
    if not isinstance(device, dict):
        return {
            "id": "",
            "name": "",
            "type": "",
            "volume_percent": 0,
            "is_active": False,
            "is_restricted": False,
            "is_preferred_local": False,
        }

    name = str(device.get("name") or "")
    lower_name = name.lower()
    return {
        "id": str(device.get("id") or ""),
        "name": name,
        "type": str(device.get("type") or ""),
        "volume_percent": int(device.get("volume_percent") or 0),
        "is_active": bool(device.get("is_active")),
        "is_restricted": bool(device.get("is_restricted")),
        "is_preferred_local": any(token in lower_name for token in ("raspotify", "raspberrypi", "google assistant")),
    }


def _collect_playlist_items(client: object, limit: int = 20) -> list[dict]:
    playlists: list[dict] = []
    offset = 0
    page_size = 20

    while len(playlists) < limit:
        response = client.current_user_playlists(limit=min(page_size, limit - len(playlists)), offset=offset)
        items = response.get("items") if isinstance(response, dict) else []
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if isinstance(item, dict):
                playlists.append(item)
                if len(playlists) >= limit:
                    break

        next_page = response.get("next") if isinstance(response, dict) else None
        if not next_page:
            break

        offset += len(items)

    return playlists


def _normalize_audio_source(source: str) -> str:
    value = (source or "").strip().lower().replace("_", "-")
    aliases = {
        "spotify": "spotify",
        "google-assistant": "google-assistant",
        "google assistant": "google-assistant",
        "assistant": "google-assistant",
        "google": "google-assistant",
    }
    if value not in aliases:
        raise HTTPException(status_code=400, detail="Audio source must be 'spotify' or 'google-assistant'.")
    return aliases[value]


def _best_effort_release_local_audio() -> list[str]:
    actions = []
    commands: list[list[str]] = []
    if NOVA_AUDIO_RELEASE_COMMANDS:
        for raw_command in re.split(r"[\r\n;]+", NOVA_AUDIO_RELEASE_COMMANDS):
            raw_command = raw_command.strip()
            if raw_command:
                commands.append(shlex.split(raw_command))
    else:
        if shutil.which("wpctl"):
            commands.append(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
        if shutil.which("pactl"):
            commands.append(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        if shutil.which("amixer"):
            commands.extend(
                [
                    ["amixer", "-q", "sset", "Master", "unmute"],
                    ["amixer", "-q", "sset", "PCM", "unmute"],
                    ["amixer", "-q", "sset", "Speaker", "unmute"],
                    ["amixer", "-q", "sset", "Headphone", "unmute"],
                ]
            )

    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=2, check=False)
            if result.returncode == 0:
                actions.append(" ".join(command))
        except Exception:
            continue
    return actions


def _initialize_backend_once() -> None:
    global _startup_completed
    with _startup_lock:
        if _startup_completed:
            logger.info("NOVA backend initialization already completed in this process; skipping duplicate startup.")
            return

        logger.info("NOVA backend starting up on port %s", PORT)
        logger.debug("SKIP_MODEL_LOAD=%s", os.environ.get("SKIP_MODEL_LOAD", ""))
        _apply_voice_settings_to_stt(get_alert_settings_store().get_voice_settings())
        if not os.environ.get("SKIP_MODEL_LOAD"):
            logger.info("Loading chat model...")
            ai_state.load_model()
            logger.info("Chat model loaded.")

        try:
            from task_scheduler import init_scheduler
            init_scheduler(ai_state.conv_manager)
        except Exception as e:
            logger.warning("Task scheduler not started: %s", e)

        _startup_completed = True
        logger.info("NOVA backend ready.")


@asynccontextmanager
async def lifespan(_app):
    _initialize_backend_once()
    telegram_bot = start_telegram_bot()
    try:
        if telegram_bot is not None:
            telegram_bot.send_startup_notification()
        yield
    finally:
        try:
            from task_scheduler import shutdown_scheduler
            shutdown_scheduler(wait=False)
        except Exception as exc:
            logger.warning("Task scheduler shutdown failed: %s", exc)
        ai_state.shutdown()
        if telegram_bot is not None:
            telegram_bot.stop()
        else:
            stop_telegram_bot()


app = FastAPI(title="NOVA Unified Backend", lifespan=lifespan)

# Enable CORS from explicit env origins, with localhost-only defaults.
def _csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def _cors_origins() -> list[str]:
    configured = _csv_env("CORS_ALLOWED_ORIGINS")
    if configured:
        return configured

    frontend_port = os.getenv("VITE_DEV_PORT", "5173")
    backend_port = str(PORT)
    return [
        f"http://localhost:{frontend_port}",
        f"http://127.0.0.1:{frontend_port}",
        f"http://localhost:{backend_port}",
        f"http://127.0.0.1:{backend_port}",
    ]


def _cors_origin_regex() -> str | None:
    value = os.getenv("CORS_ALLOWED_ORIGIN_REGEX", "").strip()
    return value or None

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


@app.get("/")
async def root_status_page():
    """Show backend and Spotify diagnostics at the main URL."""
    details = [
        f"If Spotify login fails, open the Spotify Developer Dashboard and confirm the Redirect URI is exactly http://127.0.0.1:{PORT}/callback.",
        "If the page says Spotify is not configured, create the .env file in the NOVA project root and add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.",
        "If the GUI stays on SYNCING, make sure the backend is running in this same project folder and reachable on port 8000.",
    ]
    return _render_status_page(
        title="NOVA backend diagnostics",
        summary="This page shows the exact configuration NOVA is reading right now.",
        details=details,
    )


@app.get("/health")
async def health():
    """Simple health check for monitoring and tests."""
    return {"status": "ok"}


@app.post("/telegram/test-message", dependencies=CONTROL_AUTH)
async def telegram_test_message():
    """Send a Telegram test message to all subscribed chats."""
    bot = get_telegram_bot()
    result = bot.send_test_notification()
    if int(result.get("sent") or 0) <= 0:
        errors = result.get("errors") or []
        detail = errors[0] if isinstance(errors, list) and errors else "Telegram test message could not be sent."
        raise HTTPException(status_code=409, detail=detail)
    return {"status": "sent", **result}


def _alert_settings_response() -> dict[str, object]:
    store = get_alert_settings_store()
    settings = store.get()
    telegram_settings = store.get_telegram()
    return {
        "status": "ok",
        "alerts": settings,
        "telegram": telegram_settings,
        "regions": [{"region": region, "enabled": settings[region]} for region in ALERT_REGIONS],
    }


def _coerce_settings_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    raise HTTPException(status_code=400, detail="Alert settings values must be booleans.")


def _apply_voice_settings_to_stt(settings: dict[str, object]) -> dict[str, object]:
    apply_voice_settings = getattr(ai_state, "apply_voice_settings", None)
    if callable(apply_voice_settings):
        try:
            return dict(apply_voice_settings(settings))
        except Exception as exc:
            logger.warning("Failed to apply voice settings to runtime: %s", exc)

    language = str(settings.get("language") or "en").strip().lower()
    update_config = getattr(ai_state.stt, "update_config", None)
    if callable(update_config):
        try:
            return dict(update_config(language=language))
        except Exception as exc:
            logger.warning("Failed to apply voice settings to STT engine: %s", exc)
    return {"language": language}


def _voice_settings_response() -> dict[str, object]:
    store = get_alert_settings_store()
    settings = store.get_voice_settings()
    runtime_config = _apply_voice_settings_to_stt(settings)
    return {
        "status": "ok",
        "voice": settings,
        "runtime": runtime_config,
        "languages": [
            {"value": "en", "label": "English"},
            {"value": "sv", "label": "Swedish"},
            {"value": "auto", "label": "Auto"},
        ],
    }


def _model_settings_response() -> dict[str, object]:
    selected_model = get_chat_model_settings_store().get_selected_model()
    runtime = ai_state.get_model_runtime_status()
    return {
        "status": "ok",
        "selected_model": selected_model,
        "active_model": runtime["active_model"],
        "switching": runtime["switching"],
        "error": runtime["error"],
        "options": get_chat_model_options(),
    }


@app.get("/settings/alerts")
async def get_alert_settings():
    """Return shared ON/OFF settings for alert regions."""
    return _alert_settings_response()


@app.post("/settings/alerts", dependencies=CONTROL_AUTH)
async def update_alert_settings(request: Request):
    """Patch shared alert region settings for Telegram and the GUI."""
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

    values = payload.get("alerts") if isinstance(payload.get("alerts"), dict) else payload
    updates: dict[str, bool] = {}
    for region in ALERT_REGIONS:
        if region in values:
            updates[region] = _coerce_settings_bool(values[region])

    unknown_regions = sorted(key for key in values.keys() if key not in ALERT_REGIONS and key not in {"alerts", "telegram"})
    if unknown_regions:
        allowed = ", ".join(ALERT_REGIONS)
        raise HTTPException(status_code=400, detail=f"Unsupported alert region(s): {', '.join(unknown_regions)}. Allowed: {allowed}.")

    store = get_alert_settings_store()
    store.update(updates)
    telegram_values = payload.get("telegram")
    if isinstance(telegram_values, dict):
        unknown_telegram_keys = sorted(key for key in telegram_values.keys() if key != "startup_notifications")
        if unknown_telegram_keys:
            raise HTTPException(status_code=400, detail=f"Unsupported Telegram setting(s): {', '.join(unknown_telegram_keys)}.")
        telegram_updates = {}
        if "startup_notifications" in telegram_values:
            telegram_updates["startup_notifications"] = _coerce_settings_bool(telegram_values["startup_notifications"])
        store.update_telegram(telegram_updates)
    return _alert_settings_response()


@app.get("/settings/voice")
async def get_voice_settings():
    """Return speech-to-text settings for the GUI."""
    return _voice_settings_response()


@app.post("/settings/voice", dependencies=CONTROL_AUTH)
async def update_voice_settings(request: Request):
    """Patch speech-to-text settings and apply them to the active STT engine."""
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

    if "voice" in payload and not isinstance(payload.get("voice"), dict):
        raise HTTPException(status_code=400, detail="Voice settings must be a JSON object.")

    values = payload.get("voice") if isinstance(payload.get("voice"), dict) else payload
    unknown_keys = sorted(
        key for key in values.keys()
        if key not in {"language", "voice", "always_listening", "wake_phrases", "wake_command_mode"}
    )
    if unknown_keys:
        raise HTTPException(status_code=400, detail=f"Unsupported voice setting(s): {', '.join(unknown_keys)}.")

    try:
        get_alert_settings_store().update_voice_settings(values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _voice_settings_response()


@app.get("/settings/models")
async def get_model_settings():
    """Return selectable chat models and their current runtime status."""
    return _model_settings_response()


@app.post("/settings/models", dependencies=CONTROL_AUTH)
async def update_model_settings(request: Request):
    """Persist a chat-model choice and start replacing the active model."""
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    if not isinstance(payload, dict) or set(payload) != {"model"} or not isinstance(payload.get("model"), str):
        raise HTTPException(status_code=400, detail="Request body must contain only a string 'model' value.")

    model_id = payload["model"].strip()
    try:
        get_chat_model_spec(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        ai_state.request_model_switch(model_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    get_chat_model_settings_store().set_selected_model(model_id)
    return _model_settings_response()


@app.get("/system/stats")
async def system_stats():
    """Get current system stats (CPU, RAM, temperature)."""
    sampled_at = datetime.now()
    cache_ttl = timedelta(seconds=3)

    with _SYSTEM_STATS_CACHE_LOCK:
        cached_data = _SYSTEM_STATS_CACHE["data"]
        cached_at = _SYSTEM_STATS_CACHE["last_fetched"]
        if isinstance(cached_data, dict) and isinstance(cached_at, datetime) and sampled_at - cached_at < cache_ttl:
            return cached_data

    try:
        cpu_percent, ram, temp = await asyncio.gather(
            asyncio.to_thread(psutil.cpu_percent, interval=0.05),
            asyncio.to_thread(psutil.virtual_memory),
            asyncio.to_thread(_read_temperature_celsius),
        )
        ram_percent = ram.percent
        clock_time = sampled_at.strftime("%H:%M:%S")
        cpu_value = _finite_float(cpu_percent)
        ram_value = _finite_float(ram_percent)
        temp_value = _finite_float(temp)

        stats = {
            "time": clock_time,
            "cpu_percent": round(cpu_value, 1),
            "memory_percent": round(ram_value, 1),
            "temperature": round(temp_value, 1),
            "cpu": round(cpu_value, 1),
            "ram": round(ram_value, 1),
            "temp": round(temp_value, 1),
        }
        logger.debug("System stats sampled: %s", stats)

        with _SYSTEM_STATS_CACHE_LOCK:
            _SYSTEM_STATS_CACHE["data"] = stats
            _SYSTEM_STATS_CACHE["last_fetched"] = sampled_at

        return stats
    except Exception as e:
        logger.warning("Error getting system stats: %s", e)
        fallback = {
            "time": sampled_at.strftime("%H:%M:%S"),
            "cpu_percent": 0, "memory_percent": 0, "temperature": 0,
            "cpu": 0, "ram": 0, "temp": 0,
        }
        with _SYSTEM_STATS_CACHE_LOCK:
            _SYSTEM_STATS_CACHE["data"] = fallback
            _SYSTEM_STATS_CACHE["last_fetched"] = sampled_at
        return fallback


@app.websocket("/ws/system-stats")
async def system_stats_websocket(websocket: WebSocket):
    """Push system stats at a gentle interval to avoid noisy polling on the Pi."""
    if not await authorize_control_websocket(websocket):
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(await system_stats())
            await sleep(10)
    except WebSocketDisconnect:
        logger.info("System stats websocket disconnected")
    except Exception as exc:
        logger.debug("System stats websocket closed with error: %s", exc)


def _read_temperature_celsius() -> float:
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for entries in temps.values():
                if entries and entries[0].current is not None:
                    return float(entries[0].current)
    except (AttributeError, OSError):
        pass

    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as f:
            milli_c = f.read().strip()
        if milli_c:
            return float(milli_c) / 1000.0
    except (OSError, ValueError):
        pass

    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=1, check=False,
        )
        output = (result.stdout or "").strip()
        if output.startswith("temp=") and "'" in output:
            value = output.split("=", 1)[1].split("'", 1)[0]
            return float(value)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass

    logger.debug("Temperature sources unavailable; returning 0C.")
    return 0.0


def _finite_float(value: float, fallback: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else fallback
    except (TypeError, ValueError):
        return fallback


def _fetch_json(url: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "NOVA/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _fetch_json_post(url: str, payload: str, timeout: float = 8.0, headers: dict[str, str] | None = None) -> dict:
    req_headers = {"User-Agent": "NOVA/1.0", "Content-Type": "text/xml"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=payload.encode("utf-8"), headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

# WEATHER
@app.get("/integrations/weather")
async def weather_open_meteo(
    latitude: float = 59.3293,
    longitude: float = 18.0686,
    timezone: str = "auto"
):
    try:
        return await get_weather(
            latitude=latitude,
            longitude=longitude,
            timezone=timezone
        )

    except requests.exceptions.Timeout as exc:
        logger.warning(
            "Open-Meteo request timed out for lat=%s lon=%s: %s",
            latitude,
            longitude,
            exc
        )
        return {
            "error": "Weather service temporarily unavailable"
        }

    except requests.exceptions.RequestException as exc:
        logger.warning(
            "Open-Meteo request failed for lat=%s lon=%s: %s",
            latitude,
            longitude,
            exc
        )
        return {
            "error": "Weather service temporarily unavailable"
        }

    except Exception as exc:
        logger.warning(
            "Unexpected weather error for lat=%s lon=%s: %s",
            latitude,
            longitude,
            exc
        )
        return {
            "error": "Weather service temporarily unavailable"
        }
# NEWS AND ALERTS
@app.get("/integrations/swedish-alerts")
async def swedish_alerts(limit: int = 12, region: str = "nacka"):
    """Aggregate Sweden-focused alerts/news from official APIs."""
    return await asyncio.to_thread(fetch_swedish_alerts, limit=limit, region=region)

# SPOTIFY INTEGRATION
@app.get("/nova/spotify/login")
async def spotify_login():
    try:
        oauth = _spotify_oauth()
        return RedirectResponse(oauth.get_authorize_url())
    except HTTPException as exc:
        return _render_status_page(
            title="Spotify login is not ready",
            summary=str(exc.detail),
            details=[
                "Make sure the Spotify app credentials are stored in NOVA_PROJECT_ROOT/.env or NOVA_ENV_PATH.",
                f"Make sure Spotify is allowed to redirect to {SPOTIFY_DASHBOARD_REDIRECT_URI}.",
                "If you just changed the scopes, delete .spotify_cache and log in again so Spotify can grant the new permissions.",
                "Restart NOVA after changing .env so the backend reloads the values.",
            ],
            status_code=exc.status_code,
        )


@app.get("/callback")
async def spotify_callback(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    state: str | None = Query(default=None),
):
    query_params = request.query_params
    code = code or query_params.get("code")
    error = error or query_params.get("error")
    state = state or query_params.get("state")

    if error:
        return _render_status_page(
            title="Spotify login failed",
            summary=f"Spotify returned an error during verification: {error}",
            details=[
                f"Check that the Spotify Developer Dashboard redirect URI exactly matches http://127.0.0.1:{PORT}/callback.",
                "If Spotify complains about permissions, delete .spotify_cache and sign in again so the new playlist scope is approved.",
                "Check that you approved the login prompt in the browser that opened from NOVA.",
                "If you changed .env, restart NOVA before trying again.",
            ],
            status_code=400,
        )

    if not code:
        return _render_status_page(
            title="Spotify login missing code",
            summary="Spotify redirected back, but no authorization code was returned.",
            details=[
                f"Confirm the redirect URI in Spotify is exactly http://127.0.0.1:{PORT}/callback.",
                "If the browser already had an old Spotify session, clear .spotify_cache and try the login flow again.",
                "Confirm the browser allowed the Spotify authorization flow to finish.",
                "If this keeps happening, clear the .spotify_cache file and try again.",
            ],
            status_code=400,
        )

    try:
        oauth = _spotify_oauth()
        oauth.get_access_token(code)
    except Exception as exc:
        logger.exception("Spotify auth callback failed")
        return _render_status_page(
            title="Spotify login failed",
            summary=f"NOVA received the callback but could not exchange the code for a token: {exc}",
            details=[
                "Check that the Spotify client ID and secret in .env are correct.",
                f"Check that the redirect URI in Spotify is exactly {SPOTIFY_DASHBOARD_REDIRECT_URI}.",
                "If you changed the requested scopes, delete .spotify_cache and sign in again so Spotify can issue a fresh token.",
                "If you previously changed credentials, delete .spotify_cache and retry.",
            ],
            status_code=500,
        )

    return _render_status_page(
        title="Spotify connected",
        summary="Spotify authentication succeeded and NOVA stored the login token.",
        details=[
            "You can return to the NOVA GUI now.",
            "If the music card still shows SYNCING, refresh the GUI once.",
            "If playback controls still fail, make sure Spotify is open on a device that supports remote playback.",
        ],
    )


@app.get("/nova/spotify/now-playing")
async def spotify_now_playing():
    try:
        playback = await asyncio.to_thread(lambda: _spotify_client().current_playback())
        return _spotify_track_payload(playback)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify now-playing failed: %s", exc)
        raise HTTPException(status_code=401, detail="Spotify is not connected or the token is unavailable.")


@app.get("/nova/spotify/playlists")
async def spotify_playlists():
    now = datetime.now()
    cache_ttl = timedelta(minutes=5)

    with _PLAYLISTS_CACHE_LOCK:
        cached_data = list(_PLAYLISTS_CACHE["data"])
        cached_at = _PLAYLISTS_CACHE["last_fetched"]

    if cached_data and now - cached_at < cache_ttl:
        return cached_data[:4]


    try:
        items = await asyncio.to_thread(lambda: _collect_playlist_items(_spotify_client(), limit=10))
        playlists = [_spotify_playlist_payload(item) for item in items if isinstance(item, dict)]
        if playlists:
            with _PLAYLISTS_CACHE_LOCK:
                _PLAYLISTS_CACHE["data"] = playlists
                _PLAYLISTS_CACHE["last_fetched"] = now
        return playlists[:4] if playlists else cached_data[:4]
    except HTTPException:
        with _PLAYLISTS_CACHE_LOCK:
            cached_data = list(_PLAYLISTS_CACHE["data"])
        return cached_data[:4]
    except Exception as exc:
        status_code = getattr(exc, "http_status", None) or getattr(exc, "status_code", None)
        if status_code in (401, 403):
            with _PLAYLISTS_CACHE_LOCK:
                cached_data = list(_PLAYLISTS_CACHE["data"])
            return cached_data[:4]
        logger.warning("Spotify playlists fetch failed: %s", exc)
        with _PLAYLISTS_CACHE_LOCK:
            cached_data = list(_PLAYLISTS_CACHE["data"])
        return cached_data[:4]


@app.get("/nova/spotify/queue")
async def spotify_queue():
    try:
        payload = await asyncio.to_thread(lambda: _spotify_client().queue())
        items = payload.get("queue") if isinstance(payload, dict) else []
        return [
            _spotify_queue_track_payload(item)
            for item in (items if isinstance(items, list) else [])[:3]
            if isinstance(item, dict)
        ]
    except HTTPException:
        return []
    except Exception as exc:
        status_code = getattr(exc, "http_status", None) or getattr(exc, "status_code", None)
        if status_code not in (401, 403, 404):
            logger.warning("Spotify queue fetch failed: %s", exc)
        return []


@app.post("/nova/spotify/play-playlist/{playlist_id}", dependencies=CONTROL_AUTH)
async def spotify_play_playlist(playlist_id: str, device_id: str | None = None):
    try:
        def play_playlist_blocking():
            client = _spotify_client()
            devices_payload = client.devices()
            chosen = _select_spotify_device(devices_payload, device_id)
            chosen_id = chosen.get("id") if isinstance(chosen, dict) else None
            context_uri = f"spotify:playlist:{playlist_id}"
            if chosen_id:
                client.start_playback(device_id=chosen_id, context_uri=context_uri)
            else:
                client.start_playback(context_uri=context_uri)
            return chosen_id, chosen, client.current_playback()

        device_id, chosen_device, updated = await asyncio.to_thread(play_playlist_blocking)
        _invalidate_spotify_audio_state_cache()
        return {
            "status": "ok",
            "device_id": device_id,
            "device_name": chosen_device.get("name") if isinstance(chosen_device, dict) else None,
            **_spotify_track_payload(updated),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify playlist playback failed: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/nova/spotify/select-device/{device_id}", dependencies=CONTROL_AUTH)
async def spotify_select_device(device_id: str):
    if not device_id:
        raise HTTPException(status_code=400, detail="Device ID is required.")

    try:
        def select_device_blocking():
            client = _spotify_client()
            devices_payload = client.devices()
            selected = next(
                (
                    device
                    for device in devices_payload.get("devices", [])
                    if isinstance(device, dict) and str(device.get("id") or "") == device_id
                ),
                None,
            ) if isinstance(devices_payload, dict) else None
            if selected is None:
                raise HTTPException(status_code=404, detail="Spotify device not found.")
            client.transfer_playback(device_id=device_id, force_play=True)
            return selected, client.current_playback()

        chosen_device, updated = await asyncio.to_thread(select_device_blocking)
        _invalidate_spotify_audio_state_cache()
        return {
            "status": "ok",
            "device_id": device_id,
            "device_name": chosen_device.get("name"),
            **_spotify_track_payload(updated),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify device switch failed: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/nova/spotify/repeat", dependencies=CONTROL_AUTH)
async def spotify_repeat(state: str | None = None, device_id: str | None = None):
    try:
        def repeat_blocking():
            client = _spotify_client()
            chosen = _select_spotify_device(client.devices(), device_id)
            chosen_id = chosen.get("id") if isinstance(chosen, dict) else None
            playback = client.current_playback() or {}
            current_state = str(playback.get("repeat_state") or "off").lower()
            requested = _normalize_repeat_state(state) if state else None
            next_state = requested or _next_repeat_state(current_state)
            client.repeat(next_state, device_id=chosen_id)
            return next_state, chosen, client.current_playback()

        next_state, chosen_device, updated = await asyncio.to_thread(repeat_blocking)
        _invalidate_spotify_audio_state_cache()
        return {
            "status": "ok",
            "repeat_state": next_state,
            "device_id": chosen_device.get("id") if isinstance(chosen_device, dict) else None,
            "device_name": chosen_device.get("name") if isinstance(chosen_device, dict) else None,
            **_spotify_track_payload(updated),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify repeat failed: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/nova/spotify/shuffle", dependencies=CONTROL_AUTH)
async def spotify_shuffle(state: bool | None = None, device_id: str | None = None):
    try:
        def shuffle_blocking():
            client = _spotify_client()
            chosen = _select_spotify_device(client.devices(), device_id)
            chosen_id = chosen.get("id") if isinstance(chosen, dict) else None
            playback = client.current_playback() or {}
            current_state = bool(playback.get("shuffle_state"))
            next_state = bool(state) if state is not None else not current_state
            client.shuffle(next_state, device_id=chosen_id)
            return next_state, chosen, client.current_playback()

        next_state, chosen_device, updated = await asyncio.to_thread(shuffle_blocking)
        _invalidate_spotify_audio_state_cache()
        return {
            "status": "ok",
            "device_id": chosen_device.get("id") if isinstance(chosen_device, dict) else None,
            "device_name": chosen_device.get("name") if isinstance(chosen_device, dict) else None,
            **_spotify_track_payload(updated),
            "shuffle_state": next_state,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify shuffle failed: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/nova/spotify/duck", dependencies=CONTROL_AUTH)
async def spotify_duck(
    restore: bool = False,
    volume_percent: int | None = None,
    device_id: str | None = None,
):
    try:
        return await asyncio.to_thread(
            _spotify_duck_blocking,
            restore=restore,
            volume_percent=volume_percent,
            device_id=device_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify duck/restore failed: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc))


def _normalize_repeat_state(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in {"off", "context", "track"}:
        raise HTTPException(status_code=400, detail="Repeat state must be off, context, or track.")
    return normalized


def _next_repeat_state(current_state: str) -> str:
    sequence = ["off", "context", "track"]
    try:
        index = sequence.index((current_state or "off").lower())
    except ValueError:
        index = 0
    return sequence[(index + 1) % len(sequence)]


@app.get("/system/audio-source")
async def get_audio_source():
    return {"audio_source": AUDIO_SOURCE_STATE}


@app.get("/system/soul-status")
async def get_system_soul_status():
    return get_soul_status()


@app.get("/system/control-token", dependencies=[Depends(require_local_control_token_request)])
async def get_control_token():
    return {"token": NOVA_INTERNAL_CONTROL_TOKEN}


@app.post("/system/audio-source/{source}", dependencies=CONTROL_AUTH)
async def set_audio_source(source: str):
    global AUDIO_SOURCE_STATE
    normalized = _normalize_audio_source(source)
    previous = AUDIO_SOURCE_STATE
    AUDIO_SOURCE_STATE = normalized
    try:
        if normalized == "google-assistant":
            await asyncio.to_thread(lambda: _spotify_client().pause_playback())
            release_actions = await asyncio.to_thread(_best_effort_release_local_audio)
            _invalidate_spotify_audio_state_cache()
            logger.info("Audio source switched to Google Assistant; Spotify paused.")
            return {"status": "ok", "audio_source": AUDIO_SOURCE_STATE, "spotify_paused": True, "release_actions": release_actions, "previous_audio_source": previous}
        await asyncio.to_thread(lambda: _spotify_client().start_playback())
        _invalidate_spotify_audio_state_cache()
        logger.info("Audio source switched to Spotify; playback resumed.")
        return {"status": "ok", "audio_source": AUDIO_SOURCE_STATE, "spotify_resumed": True, "previous_audio_source": previous}
    except Exception as exc:
        status_code = getattr(exc, "http_status", None) or getattr(exc, "status_code", None)
        if status_code not in (401, 403, 503):
            logger.warning("Audio source switch failed: %s", exc)
        if normalized == "spotify":
            return {"status": "ok", "audio_source": AUDIO_SOURCE_STATE, "spotify_resumed": False, "warning": str(exc), "previous_audio_source": previous}
        return {"status": "ok", "audio_source": AUDIO_SOURCE_STATE, "spotify_paused": True, "warning": str(exc), "previous_audio_source": previous}


@app.post("/nova/spotify/toggle", dependencies=CONTROL_AUTH)
async def spotify_toggle(device_id: str | None = None):
    try:
        def toggle_blocking():
            client = _spotify_client()
            chosen = _select_spotify_device(client.devices(), device_id)
            chosen_id = chosen.get("id") if isinstance(chosen, dict) else None
            playback = client.current_playback()
            if playback and playback.get("is_playing"):
                client.pause_playback(device_id=chosen_id)
            else:
                client.start_playback(device_id=chosen_id)
            return chosen, client.current_playback()

        chosen_device, updated = await asyncio.to_thread(toggle_blocking)
        _invalidate_spotify_audio_state_cache()
        return {
            "status": "ok",
            "device_id": chosen_device.get("id") if isinstance(chosen_device, dict) else None,
            "device_name": chosen_device.get("name") if isinstance(chosen_device, dict) else None,
            **_spotify_track_payload(updated),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify toggle failed: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/nova/spotify/play", dependencies=CONTROL_AUTH)
async def spotify_play(device_id: str | None = None):
    """Start or resume Spotify without toggling active playback off."""
    try:
        def play_blocking():
            client = _spotify_client()
            chosen = _select_spotify_device(client.devices(), device_id)
            chosen_id = chosen.get("id") if isinstance(chosen, dict) else None
            playback = client.current_playback()
            if not playback or not playback.get("is_playing"):
                client.start_playback(device_id=chosen_id)
                playback = client.current_playback()
            return chosen, playback

        chosen_device, updated = await asyncio.to_thread(play_blocking)
        _invalidate_spotify_audio_state_cache()
        return {
            "status": "ok",
            "device_id": chosen_device.get("id") if isinstance(chosen_device, dict) else None,
            "device_name": chosen_device.get("name") if isinstance(chosen_device, dict) else None,
            **_spotify_track_payload(updated),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify play failed: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/nova/spotify/audio-state")
async def spotify_audio_state():
    sampled_at = datetime.now()
    cache_ttl = timedelta(seconds=4)

    with _SPOTIFY_AUDIO_STATE_CACHE_LOCK:
        cached_data = _SPOTIFY_AUDIO_STATE_CACHE["data"]
        cached_at = _SPOTIFY_AUDIO_STATE_CACHE["last_fetched"]
        if isinstance(cached_data, dict) and isinstance(cached_at, datetime) and sampled_at - cached_at < cache_ttl:
            return cached_data

    try:
        def audio_state_blocking():
            client = _spotify_client()
            return client.current_playback(), client.devices()

        playback, devices_payload = await asyncio.to_thread(audio_state_blocking)
        repeat_state = str((playback or {}).get("repeat_state") or "off")
        chosen_device = _pick_spotify_device(devices_payload)
        devices = devices_payload.get("devices") if isinstance(devices_payload, dict) else []
        result = {
            "spotify_connected": True,
            "audio_source": AUDIO_SOURCE_STATE,
            "repeat_state": repeat_state,
            "device_id": chosen_device.get("id") if isinstance(chosen_device, dict) else None,
            "device_name": chosen_device.get("name") if isinstance(chosen_device, dict) else None,
            "devices": [_device_payload(device) for device in devices if isinstance(device, dict)],
            **_spotify_track_payload(playback),
        }
    except HTTPException as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code not in (401, 403, 503):
            logger.warning("Spotify audio-state failed: %s", exc)
        result = {"spotify_connected": False, "audio_source": AUDIO_SOURCE_STATE, "repeat_state": "off", "device_id": None, "device_name": None, "devices": [], **_spotify_track_payload(None)}
    except Exception as exc:
        status_code = getattr(exc, "http_status", None) or getattr(exc, "status_code", None)
        if status_code not in (401, 403):
            logger.warning("Spotify audio-state failed: %s", exc)
        result = {"spotify_connected": False, "audio_source": AUDIO_SOURCE_STATE, "repeat_state": "off", "device_id": None, "device_name": None, "devices": [], **_spotify_track_payload(None)}

    with _SPOTIFY_AUDIO_STATE_CACHE_LOCK:
        _SPOTIFY_AUDIO_STATE_CACHE["data"] = result
        _SPOTIFY_AUDIO_STATE_CACHE["last_fetched"] = sampled_at

    return result


@app.post("/nova/spotify/next", dependencies=CONTROL_AUTH)
async def spotify_next(device_id: str | None = None):
    try:
        def next_blocking():
            client = _spotify_client()
            chosen = _select_spotify_device(client.devices(), device_id)
            chosen_id = chosen.get("id") if isinstance(chosen, dict) else None
            client.next_track(device_id=chosen_id)
            return chosen, client.current_playback()

        chosen_device, updated = await asyncio.to_thread(next_blocking)
        _invalidate_spotify_audio_state_cache()
        return {
            "status": "ok",
            "device_id": chosen_device.get("id") if isinstance(chosen_device, dict) else None,
            "device_name": chosen_device.get("name") if isinstance(chosen_device, dict) else None,
            **_spotify_track_payload(updated),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify next failed: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/nova/spotify/prev", dependencies=CONTROL_AUTH)
async def spotify_prev(device_id: str | None = None):
    try:
        def prev_blocking():
            client = _spotify_client()
            chosen = _select_spotify_device(client.devices(), device_id)
            chosen_id = chosen.get("id") if isinstance(chosen, dict) else None
            client.previous_track(device_id=chosen_id)
            return chosen, client.current_playback()

        chosen_device, updated = await asyncio.to_thread(prev_blocking)
        _invalidate_spotify_audio_state_cache()
        return {
            "status": "ok",
            "device_id": chosen_device.get("id") if isinstance(chosen_device, dict) else None,
            "device_name": chosen_device.get("name") if isinstance(chosen_device, dict) else None,
            **_spotify_track_payload(updated),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Spotify previous failed: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/shutdown", dependencies=CONTROL_AUTH)
async def shutdown():
    import threading
    import time

    def delayed_exit():
        try:
            from task_scheduler import shutdown_scheduler
            shutdown_scheduler(wait=False)
        except Exception:
            pass
        stop_telegram_bot()
        ai_state.shutdown()
        time.sleep(1)
        os._exit(0)

    threading.Thread(target=delayed_exit, daemon=True).start()
    return {"status": "shutting down..."}


if __name__ == "__main__":
    uvicorn.run(app, host=NOVA_BIND_HOST, port=PORT)
