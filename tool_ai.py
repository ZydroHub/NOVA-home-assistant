"""
Task / tool-running agent: prompt Gemma, parse tool call, run tools (functional),
then create a chat (conversation) with the tool call response.
Uses the same response flow as test_gemma.py (streaming, first_function_call_only).
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata

from huggingface_hub import hf_hub_download
from llama_cpp import Llama

logger = logging.getLogger(__name__)

# User-Agent for HTTP requests (some APIs expect a browser-like agent)
_URL_OPENER = urllib.request.build_opener()
_URL_OPENER.addheaders = [("User-Agent", "PocketAI/1.0 (Raspberry Pi)")]

# 1. Model configuration (from config)
from config import (
    LOCAL_DIR,
    PORT,
    TOOLS_PATH,
    TOOL_REPO_ID,
    TOOL_FILENAME,
    TOOL_MODEL_PATH,
)


def _env_int(name, default):
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default

REPO_ID = TOOL_REPO_ID
FILENAME = TOOL_FILENAME
MODEL_PATH = TOOL_MODEL_PATH

# 2. Auto-download if not already in models/
if not os.path.exists(MODEL_PATH):
    logger.info("Model not found at %s. Downloading from Hugging Face...", MODEL_PATH)
    os.makedirs(LOCAL_DIR, exist_ok=True)
    MODEL_PATH = hf_hub_download(
        repo_id=TOOL_REPO_ID,
        filename=TOOL_FILENAME,
        local_dir=LOCAL_DIR,
    )
    logger.info("Download complete!")

# 3. Performance settings (aligned with test_gemma.py)
PERF = {
    "n_ctx": 2048,
    "n_threads": _env_int("NOVA_TOOL_LLM_THREADS", min(4, os.cpu_count() or 4)),
    "n_threads_batch": _env_int("NOVA_TOOL_LLM_THREADS", min(4, os.cpu_count() or 4)),
    "n_batch": 512,
    "n_gpu_layers": -1,
    "use_mmap": True,
    "use_mlock": False,
    "verbose": False,
}
GEN_PERF = {
    "max_tokens": 128,
    "temperature": 0.1,
}


def first_function_call_only(text: str) -> str:
    """Keep only the first function call; normalize so it always ends with <end_function_call>."""
    end_marker = "<end_function_call>"
    idx = text.find(end_marker)
    if idx != -1:
        return text[: idx + len(end_marker)]
    if "<start_function_call>" in text and text.strip().endswith("}"):
        return text.rstrip() + "<end_function_call>"
    return text


def _parse_call_format(payload: str):
    """
    Parse Function Gemma style: call:tool_name{key:<escape>value<escape>}
    Example: call:get_weather{location:<escape>NY<escape>}
    """
    payload = payload.strip()
    if not payload.startswith("call:"):
        return None, None
    rest = payload[5:]  # after "call:"
    brace = rest.find("{")
    if brace == -1:
        return None, None
    name = rest[:brace].strip()
    args_str = rest[brace:]
    if not args_str.startswith("{") or "}" not in args_str:
        return None, None
    # Extract {...} (first balanced pair)
    depth = 0
    end = -1
    for idx, c in enumerate(args_str):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = idx
                break
    if end == -1:
        return None, None
    args_str = args_str[1:end]  # inner content
    # Parse key:<escape>value<escape> or key:value
    args = {}
    escape = "<escape>"
    pos = 0
    while pos < len(args_str):
        colon = args_str.find(":", pos)
        if colon == -1:
            break
        key = args_str[pos:colon].strip()
        pos = colon + 1
        if pos >= len(args_str):
            break
        if args_str[pos : pos + len(escape)] == escape:
            start_val = pos + len(escape)
            end_val = args_str.find(escape, start_val)
            if end_val == -1:
                break
            value = args_str[start_val:end_val]
            args[key] = value
            pos = end_val + len(escape)
            # skip comma/whitespace
            while pos < len(args_str) and args_str[pos] in " \t,":
                pos += 1
        else:
            # unquoted value (e.g. number) until comma or }
            end_val = pos
            while end_val < len(args_str) and args_str[end_val] not in ",}":
                end_val += 1
            value = args_str[pos:end_val].strip()
            args[key] = value
            pos = end_val
            while pos < len(args_str) and args_str[pos] in " \t,":
                pos += 1
    return name or None, args if args else {}


def parse_function_call(raw_call: str):
    """
    Extract tool name and arguments from model output between <start_function_call> and <end_function_call>.
    Supports: (1) call:name{key:<escape>value<escape>} and (2) JSON {"name": "...", "arguments": {...}}.
    Returns (name, arguments dict) or (None, None) if parsing fails.
    """
    start_marker = "<start_function_call>"
    end_marker = "<end_function_call>"
    i = raw_call.find(start_marker)
    j = raw_call.find(end_marker)
    if i == -1 or j == -1 or j <= i:
        return None, None
    payload = raw_call[i + len(start_marker) : j].strip()

    # Try Function Gemma "call:name{...}" format first (what the model actually outputs)
    name, args = _parse_call_format(payload)
    if name:
        return name, args

    # Fall back to JSON format
    for candidate in (payload, _extract_json_object(payload)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            name = data.get("name")
            args = data.get("arguments")
            if isinstance(args, str):
                args = json.loads(args) if args.strip() else {}
            if not name:
                continue
            return name, args or {}
        except (json.JSONDecodeError, TypeError):
            continue
    logger.warning("[tool_ai] Could not parse tool call. Raw payload: %r", payload[:500])
    return None, None


def _extract_json_object(text: str) -> str:
    """Extract the first complete {...} from text (handles extra newlines/trailing content)."""
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    for i, c in enumerate(text[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


# --- Functional tool implementations ---

def _http_get(url: str, timeout: float = 10.0) -> str:
    """Fetch URL and return response body as string. Raises on failure."""
    req = urllib.request.Request(url)
    with _URL_OPENER.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _local_api_json(path: str, *, method: str = "GET", timeout: float = 10.0) -> dict:
    base_url = os.getenv("NOVA_API_BASE_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
    headers = {"Accept": "application/json"}
    if method.upper() != "GET":
        token_payload = json.loads(_http_get(f"{base_url}/system/control-token", timeout=timeout))
        token = str(token_payload.get("token") or "").strip()
        if not token:
            raise RuntimeError("NOVA control token is unavailable.")
        headers["X-NOVA-Token"] = token

    request = urllib.request.Request(
        f"{base_url}/{path.lstrip('/')}",
        headers=headers,
        method=method.upper(),
    )
    try:
        with _URL_OPENER.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            detail = str(json.loads(detail).get("detail") or detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise RuntimeError(detail or f"NOVA API returned HTTP {exc.code}.") from exc


def run_get_weather(arguments: dict) -> str:
    location = (arguments.get("location") or "unknown").strip() or "unknown"
    logger.info("[tool] get_weather(location=%s)", location)
    try:
        # Geocode via Open-Meteo (no API key)
        geo_url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
            {"name": location, "count": 1, "language": "en", "format": "json"}
        )
        geo_data = json.loads(_http_get(geo_url))
        results = geo_data.get("results") or []
        if not results:
            return f"Weather: no location found for '{location}'."
        lat = results[0]["latitude"]
        lon = results[0]["longitude"]
        name = results[0].get("name", location)
        # Current weather
        weather_url = (
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                }
            )
        )
        weather_data = json.loads(_http_get(weather_url))
        cur = weather_data.get("current", {})
        temp = cur.get("temperature_2m")
        humidity = cur.get("relative_humidity_2m")
        wind = cur.get("wind_speed_10m")
        code = cur.get("weather_code")
        # WMO codes: 0=clear, 1-3=clouds, 45/48=fog, 51-67=rain/drizzle, 71-77=snow, 80-99=showers/thunder
        if code == 0:
            conditions = "Clear"
        elif code in (1, 2, 3):
            conditions = "Partly cloudy" if code == 1 else "Cloudy"
        elif code in (45, 48):
            conditions = "Foggy"
        elif 51 <= code <= 67:
            conditions = "Rain/Drizzle"
        elif 71 <= code <= 77:
            conditions = "Snow"
        else:
            conditions = "Precipitation"
        return (
            f"Weather for {name}: {conditions}, {temp}°C, humidity {humidity}%, wind {wind} km/h."
        )
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError) as e:
        return f"Weather for {location}: error — {e}"


def run_activate_security_mode(arguments: dict) -> str:
    logger.info("[tool] activate_security_mode()")
    return "Security mode activated"


def run_web_search(arguments: dict) -> str:
    query = (arguments.get("query") or "").strip()
    logger.info("[tool] web_search(query=%s)", query)
    if not query:
        return "Web search: no query provided."
    # Prefer ddgs package for real web results (title + snippet + URL)
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=6))
        if not results:
            return f"Web search for '{query}': no results found."
        parts = []
        for r in results:
            title = (r.get("title") or "").strip()
            body = (r.get("body") or "").strip()
            href = (r.get("href") or "").strip()
            line = f"- {title or 'Result'}"
            if body:
                line += f": {body[:180]}" + ("..." if len(body) > 180 else "")
            if href:
                line += f"\n  Link: {href}"
            parts.append(line)
        return f"Web search results for '{query}':\n\n" + "\n\n".join(parts)
    except ImportError:
        pass  # Fall back to Instant Answer API
    except Exception as e:
        logger.warning("[tool] web_search DDGS error: %s", e)
    # Fallback: DuckDuckGo Instant Answer API (limited; often empty for generic queries)
    try:
        url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode({"q": query, "format": "json"})
        data = json.loads(_http_get(url))
        parts = []
        if data.get("AbstractText"):
            parts.append(data["AbstractText"])
        if data.get("AbstractURL"):
            parts.append(f"Source: {data['AbstractURL']}")
        for t in (data.get("RelatedTopics") or [])[:5]:
            if isinstance(t, dict) and t.get("Text"):
                parts.append(f"- {t['Text']}")
            elif isinstance(t, str):
                parts.append(f"- {t}")
        if not parts:
            return f"Web search for '{query}': no snippets returned. Install ddgs for full web results: pip install ddgs"
        return f"Web search results for '{query}':\n\n" + "\n\n".join(parts)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        return f"Web search for '{query}': error — {e}"


def run_network_scan(arguments: dict) -> str:
    logger.info("[tool] network_scan()")
    try:
        out = subprocess.run(
            ["ip", "neigh", "show"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if out.returncode != 0 and out.stderr:
            return f"Network scan failed: {out.stderr.strip()}"
        lines = [l for l in out.stdout.strip().splitlines() if l and "REACHABLE" in l or "STALE" in l or "DELAY" in l]
        if not lines:
            # Fallback: /proc/net/arp (IP, MAC only)
            with open("/proc/net/arp", "r") as f:
                arp_lines = f.read().strip().splitlines()[1:]
            devices = []
            for line in arp_lines:
                parts = line.split()
                if len(parts) >= 6 and parts[3] != "00:00:00:00:00:00":
                    devices.append(f"{parts[0]}  {parts[3]}")
            if not devices:
                return "Network scan: no ARP entries found."
            return "Network scan (ARP):\n" + "\n".join(devices)
        # Parse "IP dev IF lladdr MAC REACHABLE"
        devices = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 5:
                ip, mac = parts[0], parts[4]
                devices.append(f"{ip}  {mac}")
        return "Network scan:\n" + "\n".join(devices) if devices else "Network scan: no devices found."
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return f"Network scan failed: {e}"


def run_play_music(arguments: dict) -> str:
    logger.info("[tool] play_music()")
    try:
        result = _local_api_json("/nova/spotify/play", method="POST")
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        return f"I could not start Spotify music: {exc}"

    title = str(result.get("title") or "").strip()
    artist = str(result.get("artist") or "").strip()
    if title and artist:
        return f"Playing {title} by {artist}."
    if title:
        return f"Playing {title}."
    return "Spotify playback started."


def run_pause_music(arguments: dict) -> str:
    logger.info("[tool] pause_music()")
    try:
        result = _local_api_json("/nova/spotify/pause", method="POST")
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        return f"I could not pause Spotify music: {exc}"

    title = str(result.get("title") or "").strip()
    artist = str(result.get("artist") or "").strip()
    if title and artist:
        return f"Paused {title} by {artist}."
    if title:
        return f"Paused {title}."
    return "Spotify music paused."


def run_lower_music_volume(arguments: dict) -> str:
    logger.info("[tool] lower_music_volume()")
    amount = _normalize_volume_delta_amount(arguments)
    try:
        result = _local_api_json(f"/nova/spotify/volume?delta=-{amount}", method="POST")
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        return f"I could not lower Spotify volume: {exc}"

    volume = result.get("volume_percent")
    if isinstance(volume, int):
        return f"Spotify volume lowered to {volume}%."
    return "Spotify volume lowered."


def run_raise_music_volume(arguments: dict) -> str:
    logger.info("[tool] raise_music_volume()")
    amount = _normalize_volume_delta_amount(arguments)
    try:
        result = _local_api_json(f"/nova/spotify/volume?delta={amount}", method="POST")
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        return f"I could not raise Spotify volume: {exc}"

    volume = result.get("volume_percent")
    if isinstance(volume, int):
        return f"Spotify volume raised to {volume}%."
    return "Spotify volume raised."


def _normalize_volume_delta_amount(arguments: dict) -> int:
    raw_amount = arguments.get("percent") if isinstance(arguments, dict) else None
    try:
        amount = int(raw_amount)
    except (TypeError, ValueError):
        amount = 10
    return max(1, min(100, abs(amount)))


def run_get_current_music(arguments: dict) -> str:
    logger.info("[tool] get_current_music()")
    try:
        state = _local_api_json("/nova/spotify/audio-state")
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        return f"I could not check Spotify: {exc}"

    if not state.get("spotify_connected"):
        return "Spotify is not connected right now."

    title = str(state.get("title") or "").strip()
    artist = str(state.get("artist") or "").strip()
    if not state.get("is_playing"):
        if title and artist:
            return f"No music is playing right now. {title} by {artist} is paused."
        if title:
            return f"No music is playing right now. {title} is paused."
        return "No music is playing right now."
    if title and artist:
        return f"You are listening to {title} by {artist}."
    if title:
        return f"You are listening to {title}."
    return "Spotify is playing, but the current track name is unavailable."


TOOL_RUNNERS = {
    "get_weather": run_get_weather,
    "activate_security_mode": run_activate_security_mode,
    "web_search": run_web_search,
    "network_scan": run_network_scan,
    "play_music": run_play_music,
    "pause_music": run_pause_music,
    "lower_music_volume": run_lower_music_volume,
    "raise_music_volume": run_raise_music_volume,
    "get_current_music": run_get_current_music,
}


def _match_builtin_command(prompt: str) -> str | None:
    match = _match_builtin_command_with_args(prompt)
    return match[0] if match else None


def _match_builtin_command_with_args(prompt: str) -> tuple[str, dict] | None:
    normalized = unicodedata.normalize("NFKD", str(prompt or "").lower())
    normalized = normalized.encode("ascii", errors="ignore").decode("ascii")
    normalized = re.sub(r"(?<!\w)\+\s*(\d{1,3})", r"plus \1", normalized)
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    current_music_phrases = (
        "what song is playing",
        "what music is playing",
        "whats the music right now",
        "what is the music right now",
        "what am i listening to",
        "which track is this",
        "who is this artist",
        "currently playing on spotify",
        "tell me the current song",
        "vilken lat spelas",
        "vad lyssnar jag pa",
        "vad spelas pa spotify",
        "vilken musik spelar",
    )
    if any(phrase in normalized for phrase in current_music_phrases):
        return "get_current_music", {}

    play_music_phrases = (
        "play music",
        "start the music",
        "resume the music",
        "put some music on",
        "play spotify",
        "turn the music on",
        "spela musik",
        "starta musiken",
        "fortsatt spela musiken",
        "satt pa spotify",
        "satt pa musik",
    )
    if any(phrase in normalized for phrase in play_music_phrases):
        return "play_music", {}

    pause_music_phrases = (
        "turn off the music",
        "turn music off",
        "stop the music",
        "pause the music",
        "pause music",
        "stop music",
        "turn off spotify",
        "stang av musiken",
        "pausa musiken",
        "stoppa musiken",
    )
    if any(phrase in normalized for phrase in pause_music_phrases):
        return "pause_music", {}

    lower_volume_phrases = (
        "lower the volume",
        "turn down the volume",
        "lower music volume",
        "turn the music down",
        "make the music quieter",
        "sank volymen",
        "sank musiken",
        "sank med",
        "lagre volym",
        "skruva ner volymen",
        "lower by",
    )
    if any(phrase in normalized for phrase in lower_volume_phrases):
        return "lower_music_volume", {"percent": _extract_volume_delta_percent(normalized)}

    raise_volume_phrases = (
        "raise the volume",
        "turn up the volume",
        "increase the volume",
        "raise music volume",
        "turn the music up",
        "make the music louder",
        "hoj volymen",
        "hoj musiken",
        "hoj med",
        "hogre volym",
        "skruva upp volymen",
        "raise by",
        "increase by",
        "plus",
    )
    if any(phrase in normalized for phrase in raise_volume_phrases) or _has_explicit_positive_volume_delta(normalized):
        return "raise_music_volume", {"percent": _extract_volume_delta_percent(normalized)}
    return None


def _extract_volume_delta_percent(normalized_prompt: str) -> int:
    percent_patterns = (
        r"\b(?:by|with|med)\s+(\d{1,3})\s*(?:percent|procent)?\b",
        r"\b(\d{1,3})\s*(?:percent|procent)\b",
        r"\b(\d{1,3})\s*$",
    )
    for pattern in percent_patterns:
        match = re.search(pattern, normalized_prompt)
        if match:
            try:
                return max(1, min(100, int(match.group(1))))
            except (TypeError, ValueError):
                break
    return 10


def _has_explicit_positive_volume_delta(normalized_prompt: str) -> bool:
    return bool(re.search(r"(?:^|\s)(?:\+|plus)\s*\d{1,3}\s*(?:percent|procent)?\b", normalized_prompt))


def run_tool(name: str, arguments: dict) -> str:
    runner = TOOL_RUNNERS.get(name)
    if not runner:
        logger.warning("[tool] unknown tool: %s(%s)", name, arguments)
        return f"Unknown tool: {name}"
    return runner(arguments)


# Cached model and tools for run_task_for_backend (lazy load)
_llm_cache = None
_chat_tools_cache = None


def _get_llm_and_tools():
    """Load Gemma and tools once; cache for run_task_for_backend."""
    global _llm_cache, _chat_tools_cache
    if _llm_cache is not None and _chat_tools_cache is not None:
        return _llm_cache, _chat_tools_cache
    if not os.path.exists(TOOLS_PATH):
        raise FileNotFoundError(f"Tools file not found: {TOOLS_PATH}")
    with open(TOOLS_PATH, "r") as f:
        tools = json.load(f)
    _chat_tools_cache = [{"type": "function", "function": t} for t in tools]
    model_path = MODEL_PATH
    if not os.path.exists(model_path):
        logger.info("Model not found at %s. Downloading...", model_path)
        os.makedirs(LOCAL_DIR, exist_ok=True)
        model_path = hf_hub_download(repo_id=REPO_ID, filename=FILENAME, local_dir=LOCAL_DIR)
    logger.info("[tool_ai] Loading FunctionGemma: %s", model_path)
    _llm_cache = Llama(
        model_path=model_path,
        n_ctx=PERF["n_ctx"],
        n_threads=PERF["n_threads"],
        n_threads_batch=PERF["n_threads_batch"],
        n_batch=PERF["n_batch"],
        n_gpu_layers=PERF["n_gpu_layers"],
        use_mmap=PERF["use_mmap"],
        use_mlock=PERF["use_mlock"],
        verbose=PERF["verbose"],
    )
    return _llm_cache, _chat_tools_cache


def preload_tool_model() -> None:
    """Load Function Gemma and tools at startup so first tool call is fast. Safe to call multiple times."""
    try:
        _get_llm_and_tools()
        logger.info("[tool_ai] Function Gemma preloaded.")
    except Exception as e:
        logger.warning("[tool_ai] Preload skipped or failed: %s", e)


def run_task_for_backend(prompt: str) -> tuple:
    """
    Run tool_ai for a single user prompt from chat_ai (voice or chat).
    Loads model/tools on first call. Tools print to terminal.
    Returns (tool_call_raw_or_none, tool_result_or_none).
    If no tool call, returns (None, None).
    """
    builtin_match = _match_builtin_command_with_args(prompt)
    if builtin_match:
        builtin_command, arguments = builtin_match
        args_payload = "".join(
            f"{key}:{value}"
            for key, value in (arguments or {}).items()
        )
        tool_call = f"<start_function_call>call:{builtin_command}{{{args_payload}}}<end_function_call>"
        return tool_call, run_tool(builtin_command, arguments)

    llm, chat_tools = _get_llm_and_tools()
    return run_task(llm, chat_tools, prompt)


def run_task(llm, chat_tools, user_prompt: str):
    """
    Run one turn: user prompt -> Gemma (with tools) -> first tool call -> execute tool.
    Returns (tool_call_raw, tool_result) for building the chat. If no tool call, returns (None, None).
    """
    messages = [
        {"role": "developer", "content": "You are a model that can do function calling with the provided functions."},
        {"role": "user", "content": user_prompt},
    ]

    stream = llm.create_chat_completion(
        messages=messages,
        tools=chat_tools,
        max_tokens=GEN_PERF["max_tokens"],
        temperature=GEN_PERF["temperature"],
        stop=["<end_function_call>", "<eos>"],
        stream=True,
    )
    content_parts = []
    for chunk in stream:
        choice = chunk.get("choices", [{}])[0]
        delta = choice.get("delta", {})
        text = delta.get("content") or ""
        if text:
            content_parts.append(text)

    raw = "".join(content_parts)
    tool_call_raw = first_function_call_only(raw)
    if "<start_function_call>" not in tool_call_raw:
        logger.debug("Model did not produce a tool call.")
        return None, None

    name, arguments = parse_function_call(tool_call_raw)
    if not name:
        logger.warning("Could not parse tool call from model output.")
        return tool_call_raw, None

    logger.info("Tool call: %s(%s)", name, arguments)
    result = run_tool(name, arguments)
    return tool_call_raw, result


def create_chat_via_api(title: str, messages: list, api_base: str = "http://127.0.0.1:8000"):
    """Create a conversation with the given messages via the backend API."""
    try:
        import urllib.request
        payload = json.dumps({"title": title, "messages": messages}).encode("utf-8")
        req = urllib.request.Request(
            f"{api_base}/conversations",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data
    except Exception as e:
        logger.warning("Failed to create conversation via API: %s", e)
        return None


def run_backend_mode(prompt: str) -> None:
    """
    Run tool task and print a single JSON line to stdout for chat_ai subprocess.
    Used when invoked as: python tool_ai.py --backend-mode < prompt.txt
    """
    try:
        tool_call_raw, tool_result = run_task_for_backend(prompt)
        out = {"tool_call_raw": tool_call_raw, "tool_result": tool_result}
        print(json.dumps(out), flush=True)
    except Exception as e:
        logger.exception("Backend mode error: %s", e)
        out = {"error": str(e), "tool_call_raw": None, "tool_result": None}
        print(json.dumps(out), flush=True)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run Gemma with tools; create a chat with the tool call response.")
    parser.add_argument("prompt", nargs="?", help="User prompt (e.g. task message)")
    parser.add_argument("--no-create-chat", action="store_true", help="Do not POST to create a conversation")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="Backend API base URL")
    parser.add_argument("--backend-mode", action="store_true", help="Read prompt from stdin, print JSON result to stdout (for chat backend subprocess)")
    args = parser.parse_args()

    if args.backend_mode:
        prompt = sys.stdin.read().strip()
        if not prompt:
            print(json.dumps({"error": "No prompt on stdin", "tool_call_raw": None, "tool_result": None}), flush=True)
            return 1
        run_backend_mode(prompt)
        return 0

    prompt = args.prompt
    if not prompt:
        prompt = input("Prompt (task message): ").strip()
    if not prompt:
        logger.warning("No prompt provided.")
        return 1

    # Load tools (same as test_gemma.py)
    if not os.path.exists(TOOLS_PATH):
        logger.error("Error: Tools file not found at %s", TOOLS_PATH)
        return 1
    with open(TOOLS_PATH, "r") as f:
        tools = json.load(f)
    chat_tools = [{"type": "function", "function": t} for t in tools]

    # Load model
    logger.info("Loading FunctionGemma model: %s...", MODEL_PATH)
    llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=PERF["n_ctx"],
        n_threads=PERF["n_threads"],
        n_threads_batch=PERF["n_threads_batch"],
        n_batch=PERF["n_batch"],
        n_gpu_layers=PERF["n_gpu_layers"],
        use_mmap=PERF["use_mmap"],
        use_mlock=PERF["use_mlock"],
        verbose=PERF["verbose"],
    )

    # Run task: prompt -> model -> tool call -> run tool
    tool_call_raw, tool_result = run_task(llm, chat_tools, prompt)

    # Build chat messages (role + content only; backend can add timestamp if needed)
    chat_messages = [
        {"role": "user", "content": prompt},
    ]
    if tool_call_raw:
        chat_messages.append({"role": "assistant", "content": tool_call_raw})
    if tool_result is not None:
        chat_messages.append({"role": "assistant", "content": f"[Tool result] {tool_result}"})

    if not args.no_create_chat and chat_messages:
        title = (prompt[:30] + "…") if len(prompt) > 30 else prompt
        conv = create_chat_via_api(title, chat_messages, api_base=args.api_base)
        if conv:
            logger.info("Created conversation: %s — %s", conv.get('id'), conv.get('title', ''))
        else:
            logger.info("Chat messages (API create skipped or failed):")
            for m in chat_messages:
                logger.info("  %s: %s", m['role'], m['content'][:80] + "…" if len(m["content"]) > 80 else m['content'])
    else:
        logger.info("Chat messages:")
        for m in chat_messages:
            logger.info("  %s: %s", m['role'], m['content'][:80] + "…" if len(m["content"]) > 80 else m['content'])

    return 0


if __name__ == "__main__":
    exit(main())
