"""
Chat and voice pipeline: conversation CRUD, WebSocket chat, STT → LLM → TTS.
"""
import asyncio
import atexit
import base64
import contextlib
import copy
import json
import logging
import os
import queue
import re
import ipaddress
import socket
import subprocess
import sys
import time
import threading
import uuid
from typing import Any, Dict, List, Optional

from quiet_io import silence_stderr_fd

from fastapi import APIRouter, Depends, Header, Request, WebSocket, WebSocketDisconnect, HTTPException
from huggingface_hub import hf_hub_download
try:
    from llama_cpp import Llama
except ImportError as exc:
    raise ImportError(
        "Missing dependency 'llama_cpp' (package: llama-cpp-python). "
        f"Install with: {sys.executable} -m pip install -r requirements.txt"
    ) from exc
from pydantic import BaseModel
from wake_word import DEFAULT_WAKE_COMMAND_MODE, DEFAULT_WAKE_PHRASES, WakeWordDetector
from soul import build_soul_system_prompt, register_memory_duplicate_checker, remember_from_interaction

with silence_stderr_fd():
    from stt_whisper import STTEngine as WhisperEngine
    from stt_vosk import STTEngine as VoskEngine
    from tts_piper import PocketAudio

logger = logging.getLogger(__name__)


async def _safe_ws_send_json(websocket: WebSocket, payload: dict, context: str = "") -> bool:
    """Send JSON over WS and return False if the socket is no longer writable."""
    try:
        await websocket.send_json(payload)
        return True
    except WebSocketDisconnect:
        if context:
            logger.info("WebSocket disconnected while sending %s", context)
        else:
            logger.info("WebSocket disconnected while sending")
        return False
    except RuntimeError as exc:
        if "close message has been sent" in str(exc):
            if context:
                logger.info("WebSocket already closed while sending %s", context)
            else:
                logger.info("WebSocket already closed while sending")
            return False
        raise


VOICE_EMPTY_REPLY_FALLBACK = "I heard you, but I could not create a spoken reply. Please try again."
VOICE_TTS_END_MARKS = ".!?,;:\n"
VOICE_TTS_MIN_CLAUSE_CHARS = 8
CHAT_CONTEXT_KEEP_MESSAGES = int(os.getenv("NOVA_CHAT_CONTEXT_KEEP_MESSAGES", "12"))
CONVERSATION_SAVE_DEBOUNCE_SECONDS = float(os.getenv("NOVA_CONVERSATION_SAVE_DEBOUNCE_SECONDS", "2.0"))
WAKE_FOLLOWUP_CAPTURE_SECONDS = max(1.0, float(os.getenv("NOVA_WAKE_FOLLOWUP_CAPTURE_SECONDS", "6.0")))


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


NOVA_LLM_THREADS = _env_int("NOVA_LLM_THREADS", min(4, os.cpu_count() or 4))
_STREAM_DONE = object()


class _NullSpeechEngine:
    model = None
    listening = False
    language = "en"

    def load_model(self):
        return None

    def get_config(self):
        return {"model_size": None, "language": self.language}

    def update_config(self, *, language=None):
        if language is not None:
            normalized_language = str(language or "").strip().lower()
            self.language = "auto" if normalized_language in {"", "auto", "none", "null"} else normalized_language
        return self.get_config()

    def start_capture(self):
        self.listening = False

    def stop_and_transcribe(self):
        return ""

    def start_listening(self, callback=None):
        self.listening = False

    def stop_listening(self):
        return ""


class _NullAudio:
    sample_rate = 22050

    def iter_pcm_chunks(self, text, abort_event=None):
        return iter(())

    def clear_queue(self):
        return None

    def interrupt(self):
        return None

    def set_queue_drained_callback(self, callback):
        return None

    def enqueue_text(self, text):
        return 0


class VoiceInterruptController:
    """Tracks active voice generations and cancels their shared abort events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._events: set[asyncio.Event] = set()

    def begin(self, abort_event: asyncio.Event) -> int:
        with self._lock:
            self._events.add(abort_event)
            return self._generation

    def finish(self, abort_event: asyncio.Event) -> None:
        with self._lock:
            self._events.discard(abort_event)

    def interrupt(self) -> int:
        with self._lock:
            self._generation += 1
            events = list(self._events)
        for event in events:
            event.set()
        return self._generation

    def is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation


# Semantic router: route prompt to qwen_basic or function_gemma
def _init_semantic_router() -> None:
    try:
        from semantic_router_ai import init_router
        init_router()
        logger.info("Semantic router initialized for in-memory route checks.")
    except Exception as e:
        logger.warning("semantic router initialization failed: %s", e)


def _get_route(prompt: str) -> str:
    try:
        from semantic_router_ai import get_route
        return get_route(prompt)
    except Exception as e:
        logger.warning("semantic router failed: %s", e)
        return "qwen_basic"


def _pop_voice_tts_units(buffer: str, final: bool = False) -> tuple[List[str], str]:
    """Split generated text into low-latency speakable clauses."""
    units: List[str] = []
    remaining = buffer
    while True:
        split_at = -1
        for idx, char in enumerate(remaining):
            if char in VOICE_TTS_END_MARKS and idx + 1 >= VOICE_TTS_MIN_CLAUSE_CHARS:
                split_at = idx + 1
                break
        if split_at < 0:
            break
        unit = remaining[:split_at].strip()
        remaining = remaining[split_at:].strip()
        if unit:
            units.append(unit)

    if final and remaining.strip():
        units.append(remaining.strip())
        remaining = ""

    return units, remaining


def _run_tool_ai_subprocess(prompt: str, cancel_event: threading.Event | None = None) -> tuple:
    """
    Send a tool request to a long-lived worker so FunctionGemma stays warm.
    The worker remains a separate process for isolation, but avoids model reload
    latency on every tool call.
    """
    return _TOOL_WORKER.request(prompt, cancel_event=cancel_event)


class _ToolAIWorker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc = None

    def _start_locked(self) -> None:
        if self._proc and self._proc.poll() is None:
            return

        worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_worker.py")
        self._proc = subprocess.Popen(
            [sys.executable, "-u", worker_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            cwd=os.path.dirname(os.path.abspath(worker_path)),
        )

    def _stop_locked(self) -> None:
        if not self._proc:
            return
        proc = self._proc
        self._proc = None
        try:
            if proc.stdin:
                with contextlib.suppress(Exception):
                    proc.stdin.close()
            if proc.stdout:
                with contextlib.suppress(Exception):
                    proc.stdout.close()
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()
                proc.wait(timeout=1)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def request(self, prompt: str, timeout: float = 120.0, cancel_event: threading.Event | None = None) -> tuple:
        with self._lock:
            try:
                self._start_locked()
                if not self._proc or not self._proc.stdin or not self._proc.stdout:
                    return None, "Tool worker failed to start."

                request_id = str(uuid.uuid4())
                self._proc.stdin.write(json.dumps({"id": request_id, "prompt": prompt}, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()

                line_queue: queue.Queue = queue.Queue(maxsize=1)

                def read_line() -> None:
                    try:
                        line_queue.put(self._proc.stdout.readline())
                    except Exception as exc:
                        line_queue.put(exc)

                threading.Thread(target=read_line, daemon=True).start()
                deadline = time.monotonic() + timeout
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        self._stop_locked()
                        return None, "Tool call interrupted."
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._stop_locked()
                        return None, "Tool call timed out."
                    try:
                        line = line_queue.get(timeout=min(0.1, remaining))
                        break
                    except queue.Empty:
                        continue

                if isinstance(line, Exception):
                    self._stop_locked()
                    return None, f"Tool worker read error: {line}"
                if not line:
                    self._stop_locked()
                    return None, "Tool worker stopped unexpectedly."

                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning("tool worker invalid JSON: %s", e)
                    self._stop_locked()
                    return None, "Tool returned invalid response."

                if data.get("id") != request_id:
                    logger.warning("tool worker response id mismatch")
                    self._stop_locked()
                    return None, "Tool returned mismatched response."
                if data.get("error"):
                    return data.get("tool_call_raw"), str(data["error"])
                return data.get("tool_call_raw"), data.get("tool_result")
            except Exception as e:
                logger.exception("tool worker error: %s", e)
                self._stop_locked()
                return None, f"Tool error: {e}"


_TOOL_WORKER = _ToolAIWorker()
atexit.register(_TOOL_WORKER.stop)


# --- Model Configuration (from config) ---
from config import (
    CONVERSATIONS_FILE,
    is_valid_control_token,
)
from model_settings import DEFAULT_CHAT_MODEL_ID, get_chat_model_settings_store, get_chat_model_spec


def strip_think_for_ui(text: str) -> str:
    """Remove <think>...</think> blocks and any trailing incomplete <think> for UI display."""
    if not text or not text.strip():
        return text
    out = re.sub(r'<\s*think\s*>.*?<\s*/\s*think\s*>', '', text, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r'<\s*think\s*>[\s\S]*$', '', out, flags=re.IGNORECASE)
    out = out.replace('</think>', '').replace('<think>', '')
    return out.strip()


# --- Data Models ---
class Message(BaseModel):
    role: str
    content: str
    timestamp: float


class Conversation(BaseModel):
    id: str
    title: str
    messages: List[Message]
    updated_at: float


# --- Conversation Manager ---
class ConversationManager:
    """Persists conversations to a JSON file and provides CRUD."""

    def __init__(self, storage_path: str) -> None:
        self.storage_path = storage_path
        self._lock = threading.RLock()
        self._save_timer: Optional[threading.Timer] = None
        self.conversations: Dict[str, Any] = self.load_conversations()
        atexit.register(self.flush_conversations)

    def load_conversations(self) -> Dict[str, Any]:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r', encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Conversation storage load failed; starting with empty history: %s", exc)
                return {}
            if not isinstance(data, list):
                logger.warning("Conversation storage ignored: expected a list, got %s", type(data).__name__)
                return {}
            conversations: Dict[str, Any] = {}
            for item in data:
                if isinstance(item, dict) and item.get("id"):
                    conversations[str(item["id"])] = item
            return conversations
        return {}

    def save_conversations(self) -> None:
        self.schedule_save()

    def _write_conversations(self, snapshot: List[dict]) -> None:
        directory = os.path.dirname(os.path.abspath(self.storage_path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        temp_path = f"{self.storage_path}.tmp"
        with open(temp_path, 'w', encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        os.replace(temp_path, self.storage_path)

    def flush_conversations(self) -> None:
        with self._lock:
            if self._save_timer:
                self._save_timer.cancel()
                self._save_timer = None
            snapshot = copy.deepcopy(list(self.conversations.values()))
        self._write_conversations(snapshot)

    def schedule_save(self) -> None:
        with self._lock:
            if self._save_timer:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(CONVERSATION_SAVE_DEBOUNCE_SECONDS, self.flush_conversations)
            self._save_timer.daemon = True
            self._save_timer.start()

    def create_conversation(self, title: str = "New Chat", messages: Optional[List[dict]] = None) -> dict:
        with self._lock:
            conv_id = str(uuid.uuid4())
            new_conv = {
                "id": conv_id,
                "title": title,
                "messages": list(messages) if messages else [],
                "updated_at": time.time()
            }
            self.conversations[conv_id] = new_conv
            self.save_conversations()
            return copy.deepcopy(new_conv)

    def get_conversation(self, conv_id: str) -> Optional[dict]:
        with self._lock:
            conv = self.conversations.get(conv_id)
            return copy.deepcopy(conv) if conv else None

    def update_conversation(self, conv_id: str, messages: List[dict]) -> None:
        with self._lock:
            if conv_id in self.conversations:
                self.conversations[conv_id]["messages"] = messages
                self.conversations[conv_id]["updated_at"] = time.time()
                self.save_conversations()

    def rename_conversation(self, conv_id: str, new_title: str) -> Optional[dict]:
        with self._lock:
            if conv_id in self.conversations:
                self.conversations[conv_id]["title"] = new_title
                self.conversations[conv_id]["updated_at"] = time.time()
                self.save_conversations()
                return copy.deepcopy(self.conversations[conv_id])
            return None

    def list_conversations(self) -> List[dict]:
        with self._lock:
            conversations = copy.deepcopy(list(self.conversations.values()))
            return sorted(conversations, key=lambda x: x['updated_at'], reverse=True)

    def delete_conversation(self, conv_id: str) -> None:
        with self._lock:
            if conv_id in self.conversations:
                del self.conversations[conv_id]
                self.save_conversations()


# --- AI State ---
class AIState:
    def __init__(self):
        self.llm = None
        if os.environ.get("SKIP_MODEL_LOAD"):
            self.stt = _NullSpeechEngine()
            self.vosk = _NullSpeechEngine()
            self.tts = _NullAudio()
        else:
            with silence_stderr_fd():
                self.stt = WhisperEngine()
                self.vosk = VoskEngine()
                self.tts = PocketAudio()
        self.conv_manager = ConversationManager(CONVERSATIONS_FILE)
        self.is_recording = False
        self.is_vosk_recording = False
        self._load_lock = threading.Lock()
        self._model_state_lock = threading.Lock()
        self._models_loaded = False
        self._active_model_id: str | None = None
        self._model_switching = False
        self._model_error = ""
        self._memory_duplicate_lock = threading.Lock()
        self.pending_voice_reply: Optional[str] = None
        self.voice_pipeline_active = False
        self._voice_state_lock = threading.Lock()
        self.voice_interrupts = VoiceInterruptController()
        self._voice_connection_lock = threading.Lock()
        self._voice_websocket: WebSocket | None = None
        self._voice_event_loop: asyncio.AbstractEventLoop | None = None
        self._voice_message_queue: asyncio.Queue | None = None
        self._wake_lock = threading.RLock()
        self._wake_settings = {
            "always_listening": True,
            "wake_phrases": list(DEFAULT_WAKE_PHRASES),
            "wake_command_mode": DEFAULT_WAKE_COMMAND_MODE,
        }
        self._wake_detector = WakeWordDetector(self._wake_settings["wake_phrases"])
        self._wake_vosk = None
        self._wake_vosk_factory = _NullSpeechEngine if os.environ.get("SKIP_MODEL_LOAD") else VoskEngine
        _init_semantic_router()
        self.voice_messages = [
            {"role": "system", "content": build_soul_system_prompt("voice")}
        ]

    def _refresh_voice_system_message(self) -> None:
        prompt = build_soul_system_prompt("voice")
        if self.voice_messages and self.voice_messages[0].get("role") == "system":
            self.voice_messages[0]["content"] = prompt
        else:
            self.voice_messages.insert(0, {"role": "system", "content": prompt})

    def _remember_from_interaction(self, user_text: str, assistant_text: str, source: str) -> None:
        try:
            result = remember_from_interaction(user_text, assistant_text)
            if result.added:
                logger.info("Soul memory updated from %s interaction; entries=%d", source, len(result.candidates))
            else:
                logger.debug("Soul memory skipped for %s interaction: %s", source, result.reason)
        except Exception as exc:
            logger.warning("Soul memory update failed for %s interaction: %s", source, exc)

    def memory_candidate_already_stored(self, candidate: str, existing_entries: tuple[str, ...]) -> bool:
        """Ask the active chat model whether a candidate is already represented in soul memory."""
        candidate = str(candidate or "").strip()
        entries = tuple(str(entry or "").strip() for entry in existing_entries if str(entry or "").strip())[-25:]
        if not candidate or not entries or self.llm is None:
            return False

        prompt = (
            "Decide if the candidate memory is already stored in the existing NOVA memories.\n"
            "Treat same durable fact or preference with different wording as DUPLICATE.\n"
            "Treat different, newer, or contradictory facts as NEW.\n"
            "Answer exactly one word: DUPLICATE or NEW.\n\n"
            f"Candidate:\n{candidate}\n\n"
            "Existing memories:\n"
            + "\n".join(f"- {entry}" for entry in entries)
        )

        try:
            with self._memory_duplicate_lock:
                result = self._current_llm().create_chat_completion(
                    messages=[
                        {"role": "system", "content": "You are a strict memory deduplication classifier."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=4,
                    temperature=0.0,
                    stop=["\n"],
                )
        except Exception as exc:
            logger.debug("Soul AI duplicate check skipped: %s", exc)
            return False

        try:
            verdict = str(result["choices"][0]["message"]["content"]).strip().upper()
        except (KeyError, IndexError, TypeError):
            return False
        return verdict.startswith("DUPLICATE")

    def classify_alert_severity(
        self,
        source: str,
        title: str,
        summary: str = "",
        location: str = "",
        published: str = "",
    ) -> str:
        """Classify a Swedish alert with the active chat model."""
        if self.llm is None:
            self.load_model()

        prompt = (
            "Rank the severity of this Swedish alert for a home alert dashboard.\n"
            "Answer exactly one word: LOW, MEDIUM, HIGH, or EXTREME.\n\n"
            "Rubric:\n"
            "LOW: minor incidents, checks, theft, traffic stops, routine matters.\n"
            "MEDIUM: clear risk or serious local event, fire, accident, ongoing crime without broad public danger.\n"
            "HIGH: serious violent event, major crime, larger accident, active danger to multiple people, large police operation.\n"
            "EXTREME: use only for the worst cases: VMA/important public warning, terrorism, school attack, mass shooting, many dead/injured, disaster, major explosion, or ongoing extreme public danger.\n"
            "A school attack is EXTREME. A VMA from Krisinformation is EXTREME.\n"
            "A single shooting, assault, robbery, or one person badly injured is usually HIGH, not EXTREME.\n\n"
            f"Source: {source}\n"
            f"Title: {title}\n"
            f"Summary: {summary}\n"
            f"Location: {location}\n"
            f"Published: {published}\n"
        )

        with self._memory_duplicate_lock:
            result = self._current_llm().create_chat_completion(
                messages=[
                    {"role": "system", "content": "You are a strict alert severity classifier. Output one label only."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4,
                temperature=0.0,
                stop=["\n", ".", ","],
            )
        try:
            return str(result["choices"][0]["message"]["content"]).strip().upper()
        except (KeyError, IndexError, TypeError):
            return "MEDIUM"

    def classify_polisen_severity(self, title: str, summary: str = "", location: str = "", published: str = "") -> str:
        """Classify a Polisen event with the active chat model."""
        return self.classify_alert_severity("Polisen", title, summary, location, published)

    def _load_chat_model(self, model_id: str) -> None:
        model = get_chat_model_spec(model_id)
        if not model.path.exists():
            logger.info("Downloading chat model %s...", model.label)
            model.path.parent.mkdir(parents=True, exist_ok=True)
            hf_hub_download(repo_id=model.repo_id, filename=model.filename, local_dir=str(model.path.parent))

        logger.info("Loading chat model %s...", model.label)
        replacement_llm = Llama(
            model_path=str(model.path),
            n_ctx=4096,
            n_threads=NOVA_LLM_THREADS,
            verbose=False,
        )
        with self._model_state_lock:
            self.llm = replacement_llm
            self._active_model_id = model.id

    def _load_speech_models(self) -> None:
        if getattr(self.stt, "model", None) is None:
            with silence_stderr_fd():
                self.stt.load_model()

        if getattr(self.vosk, "model", None) is None:
            with silence_stderr_fd():
                self.vosk.load_model()

    def load_model(self):
        with self._load_lock:
            selected_model = get_chat_model_settings_store().get_selected_model()
            if self._models_loaded and self.llm is not None and self._active_model_id == selected_model:
                logger.info("Chat AI already loaded; skipping model initialization.")
                return

            startup_model = selected_model
            selected_spec = get_chat_model_spec(selected_model)
            fallback_spec = get_chat_model_spec(DEFAULT_CHAT_MODEL_ID)
            if selected_model != DEFAULT_CHAT_MODEL_ID and not selected_spec.path.exists() and fallback_spec.path.exists():
                startup_model = DEFAULT_CHAT_MODEL_ID
                logger.info(
                    "Selected chat model %s is downloading; starting with %s until it is ready.",
                    selected_model,
                    fallback_spec.label,
                )

            self._load_chat_model(startup_model)
            self._load_speech_models()
            with self._model_state_lock:
                self._models_loaded = True
            logger.info("Chat AI Ready.")

            if startup_model != selected_model:
                self.request_model_switch(selected_model)

    def get_model_runtime_status(self) -> dict[str, object]:
        with self._model_state_lock:
            return {
                "active_model": self._active_model_id,
                "switching": self._model_switching,
                "error": self._model_error or None,
            }

    def request_model_switch(self, model_id: str) -> bool:
        """Start a non-blocking chat-model replacement. Returns True when loading starts."""
        get_chat_model_spec(model_id)
        with self._model_state_lock:
            if self._model_switching:
                raise RuntimeError("A chat model switch is already in progress.")
            if self.llm is not None and self._active_model_id == model_id:
                self._model_error = ""
                return False
            self._model_switching = True
            self._model_error = ""

        threading.Thread(
            target=self._switch_chat_model_worker,
            args=(model_id,),
            daemon=True,
            name="nova-chat-model-switch",
        ).start()
        return True

    def _switch_chat_model_worker(self, model_id: str) -> None:
        try:
            with self._load_lock:
                self._load_chat_model(model_id)
            logger.info("Chat model switched to %s.", model_id)
        except Exception as exc:
            logger.exception("Chat model switch to %s failed", model_id)
            with self._model_state_lock:
                self._model_error = f"Could not load {model_id}: {exc}"
        finally:
            with self._model_state_lock:
                self._model_switching = False

    def _current_llm(self):
        with self._model_state_lock:
            if self.llm is None:
                raise RuntimeError("Chat model is not loaded yet.")
            return self.llm

    def shutdown(self) -> None:
        """Best-effort cleanup for model-adjacent workers and audio devices."""
        self.conv_manager.flush_conversations()
        _TOOL_WORKER.stop()
        for engine_name in ("stt", "vosk", "tts", "_wake_vosk"):
            engine = getattr(self, engine_name, None)
            terminate = getattr(engine, "terminate", None)
            if callable(terminate):
                try:
                    terminate()
                except Exception as exc:
                    logger.warning("%s cleanup failed: %s", engine_name, exc)

    def interrupt_voice_pipeline(self) -> None:
        """Cancel active voice generation and purge any queued TTS work."""
        self.pending_voice_reply = None
        self.voice_interrupts.interrupt()
        clear_queue = getattr(self.tts, "clear_queue", None)
        if callable(clear_queue):
            with contextlib.suppress(Exception):
                clear_queue()
        interrupt_tts = getattr(self.tts, "interrupt", None)
        if callable(interrupt_tts):
            with contextlib.suppress(Exception):
                interrupt_tts()

    def apply_voice_settings(self, settings: dict[str, object]) -> dict[str, object]:
        """Apply persisted voice settings to active runtime components."""
        language = str(settings.get("language") or "en").strip().lower()
        update_config = getattr(self.stt, "update_config", None)
        if callable(update_config):
            stt_config = dict(update_config(language=language))
        else:
            stt_config = {"language": language}

        always_listening = bool(settings.get("always_listening", False))
        wake_phrases = settings.get("wake_phrases") or list(DEFAULT_WAKE_PHRASES)
        wake_command_mode = str(settings.get("wake_command_mode") or DEFAULT_WAKE_COMMAND_MODE).strip().lower()
        if wake_command_mode != DEFAULT_WAKE_COMMAND_MODE:
            wake_command_mode = DEFAULT_WAKE_COMMAND_MODE

        with self._wake_lock:
            self._wake_settings = {
                "always_listening": always_listening,
                "wake_phrases": list(wake_phrases) if isinstance(wake_phrases, list) else wake_phrases,
                "wake_command_mode": wake_command_mode,
            }
            self._wake_detector.update_phrases(wake_phrases)
            if always_listening:
                self._start_wake_listener_locked()
            else:
                self._stop_wake_listener_locked()

        return {
            **stt_config,
            "always_listening": always_listening,
            "wake_phrases": list(self._wake_detector.phrases),
            "wake_command_mode": wake_command_mode,
            "wake_listener": self._wake_runtime_status(),
        }

    def _wake_runtime_status(self) -> str:
        if not bool(self._wake_settings.get("always_listening")):
            return "disabled"
        if self._wake_vosk is not None and getattr(self._wake_vosk, "listening", False):
            return "listening"
        with self._voice_connection_lock:
            if self._voice_websocket is None or self._voice_message_queue is None:
                return "waiting_for_voice_client"
        if self.is_recording or self.is_vosk_recording:
            return "paused"
        return "idle"

    def wake_listener_enabled(self) -> bool:
        with self._wake_lock:
            return bool(self._wake_settings.get("always_listening"))

    def _emit_wake_word_event(self, transcript: str, is_partial: bool = False) -> None:
        with self._wake_lock:
            if not bool(self._wake_settings.get("always_listening")):
                return
            match = self._wake_detector.detect(transcript, is_partial=is_partial)
            mode = str(self._wake_settings.get("wake_command_mode") or DEFAULT_WAKE_COMMAND_MODE)
        if match is None:
            return

        command = match.command if mode == DEFAULT_WAKE_COMMAND_MODE else ""
        with self._voice_connection_lock:
            loop = self._voice_event_loop
            message_queue = self._voice_message_queue
        if loop is None or loop.is_closed() or message_queue is None:
            return
        payload = {
            "type": "__wake_word__",
            "phrase": match.phrase,
            "command": command,
            "text": match.text,
        }
        asyncio.run_coroutine_threadsafe(message_queue.put(payload), loop)

    def _start_wake_listener_locked(self) -> bool:
        if not bool(self._wake_settings.get("always_listening")):
            return False
        if self.is_recording or self.is_vosk_recording:
            return False
        with self._voice_connection_lock:
            websocket = self._voice_websocket
            loop = self._voice_event_loop
            message_queue = self._voice_message_queue
        if websocket is None or loop is None or loop.is_closed() or message_queue is None:
            return False
        if self._wake_vosk is None:
            with silence_stderr_fd():
                self._wake_vosk = self._wake_vosk_factory()
        if getattr(self._wake_vosk, "listening", False):
            return True
        try:
            logger.info("Starting wake-word listener")
            self._wake_vosk.start_listening(callback=self._emit_wake_word_event)
            if not getattr(self._wake_vosk, "listening", False):
                logger.warning("Wake-word listener did not enter listening state")
                return False
            return True
        except Exception as exc:
            logger.warning("Wake-word listener failed to start: %s", exc)
            return False

    def _stop_wake_listener_locked(self) -> None:
        if self._wake_vosk is not None and getattr(self._wake_vosk, "listening", False):
            try:
                logger.info("Stopping wake-word listener")
                # Prevent the recognizer's final flush from queuing a stale wake
                # event after Always Listening has been disabled or paused.
                self._wake_vosk.callback = None
                self._wake_vosk.stop_listening()
            except Exception as exc:
                logger.warning("Wake-word listener failed to stop cleanly: %s", exc)

    def pause_wake_listener(self) -> None:
        with self._wake_lock:
            self._stop_wake_listener_locked()

    def resume_wake_listener(self) -> bool:
        with self._wake_lock:
            return self._start_wake_listener_locked()

    def register_voice_connection(
        self,
        websocket: WebSocket,
        loop: asyncio.AbstractEventLoop,
        message_queue: asyncio.Queue | None = None,
    ) -> None:
        with self._voice_connection_lock:
            self._voice_websocket = websocket
            self._voice_event_loop = loop
            self._voice_message_queue = message_queue
        self.resume_wake_listener()

    def unregister_voice_connection(self, websocket: WebSocket) -> None:
        with self._voice_connection_lock:
            if self._voice_websocket is websocket:
                self._voice_websocket = None
                self._voice_event_loop = None
                self._voice_message_queue = None
        self.pause_wake_listener()

    async def _start_whisper_capture(self, websocket: WebSocket) -> bool:
        """Start a fresh Whisper capture and report the resulting voice status."""
        if self.is_recording:
            return True
        self.pending_voice_reply = None
        self.pause_wake_listener()
        try:
            self.is_recording = True
            self.stt.start_capture()
            if not self.stt.listening:
                self.is_recording = False
                self.resume_wake_listener()
                logger.error("Whisper capture start failed; STT engine not listening")
                await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "idle"}, context="voice_status idle after whisper start failure")
                await _safe_ws_send_json(websocket, {"type": "error", "message": "Whisper failed to start recording"}, context="whisper start failure")
                return False
            logger.info("Whisper capture active")
            await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "listening"}, context="voice_status listening whisper")
            return True
        except Exception as exc:
            self.is_recording = False
            self.resume_wake_listener()
            logger.exception("Whisper capture start error: %s", exc)
            await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "idle"}, context="voice_status idle after whisper start exception")
            await _safe_ws_send_json(websocket, {"type": "error", "message": f"Whisper start error: {exc}"}, context="whisper start exception")
            return False

    async def _stop_whisper_and_transcribe(self) -> str:
        """Stop Whisper capture without blocking the websocket event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.stt.stop_and_transcribe)

    async def _handle_voice_interrupt(
        self,
        websocket: WebSocket,
        abort_event: asyncio.Event,
        *,
        start_listening: bool = True,
        tool_cancel_event: threading.Event | None = None,
    ) -> str:
        logger.info("Voice interrupt requested; start_listening=%s", start_listening)
        abort_event.set()
        if tool_cancel_event is not None:
            tool_cancel_event.set()
        self.interrupt_voice_pipeline()
        await _safe_ws_send_json(websocket, {"type": "tts_audio_cancel"}, context="tts_audio_cancel")
        await _safe_ws_send_json(websocket, {"type": "ai_aborted"}, context="ai_aborted interrupt")
        if start_listening:
            await self._start_whisper_capture(websocket)
            return "interrupt_listening"
        await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "idle"}, context="voice_status idle after interrupt")
        return "interrupt"

    async def _handle_wake_word_event(
        self,
        websocket: WebSocket,
        abort_event: asyncio.Event,
        message_queue: asyncio.Queue,
        *,
        command_text: str = "",
    ) -> str:
        """Handle a wake-word event while the main voice loop is idle."""
        if not self.wake_listener_enabled():
            logger.info("Ignoring wake-word event while Always Listening is disabled")
            return "wake_disabled"
        self.pause_wake_listener()
        command_text = (command_text or "").strip()
        if command_text:
            logger.info("Wake word detected with direct command: %s", command_text)
            await _safe_ws_send_json(websocket, {"type": "voice_transcription", "text": command_text}, context="wake voice_transcription")
            await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "thinking"}, context="wake voice_status thinking")
            self.resume_wake_listener()
            await self.ai_response_and_speak(websocket, command_text, abort_event, message_queue)
            return "wake_command"

        logger.info("Wake word detected without trailing command; starting Whisper capture")
        capture_started = await self._start_whisper_capture(websocket)
        if capture_started:
            async def stop_followup_capture() -> None:
                await asyncio.sleep(WAKE_FOLLOWUP_CAPTURE_SECONDS)
                await message_queue.put({"type": "__wake_capture_timeout__"})

            asyncio.create_task(stop_followup_capture())
        return "wake_listening"

    async def _consume_voice_control_messages(
        self,
        websocket: WebSocket,
        message_queue: asyncio.Queue,
        abort_event: asyncio.Event,
        *,
        tool_cancel_event: threading.Event | None = None,
    ) -> str | None:
        deferred: list[dict] = []
        while not message_queue.empty():
            msg = await message_queue.get()
            msg_type = msg.get("type")
            if msg_type == "abort":
                logger.info("Voice AI execution aborted by user")
                abort_event.set()
                if tool_cancel_event is not None:
                    tool_cancel_event.set()
                self.interrupt_voice_pipeline()
                await _safe_ws_send_json(websocket, {"type": "tts_audio_cancel"}, context="tts_audio_cancel abort")
                return "abort"
            if msg_type == "interrupt_voice":
                return await self._handle_voice_interrupt(
                    websocket,
                    abort_event,
                    start_listening=msg.get("start_listening", True),
                    tool_cancel_event=tool_cancel_event,
                )
            if msg_type == "__wake_word__":
                if not self.wake_listener_enabled():
                    logger.info("Ignoring queued wake-word event while Always Listening is disabled")
                    continue
                self.pause_wake_listener()
                command_text = str(msg.get("command") or "").strip()
                if command_text:
                    await self._handle_voice_interrupt(
                        websocket,
                        abort_event,
                        start_listening=False,
                        tool_cancel_event=tool_cancel_event,
                    )
                    await message_queue.put({"type": "__wake_word_command__", "command": command_text})
                    return "wake_command_queued"
                return await self._handle_voice_interrupt(
                    websocket,
                    abort_event,
                    start_listening=True,
                    tool_cancel_event=tool_cancel_event,
                )
            if msg_type == "__disconnect__":
                logger.info("Voice websocket disconnected during active pipeline")
                abort_event.set()
                if tool_cancel_event is not None:
                    tool_cancel_event.set()
                self.interrupt_voice_pipeline()
                return "disconnect"
            deferred.append(msg)
        for msg in deferred:
            await message_queue.put(msg)
        return None

    async def generate_response(self, messages, max_tokens=2048):
        """Generate a response """
        llm_messages = self._build_llm_messages(messages, mode="chat")

        loop = asyncio.get_event_loop()
        llm = self._current_llm()
        response = await loop.run_in_executor(None, lambda: llm.create_chat_completion(
            messages=llm_messages,
            max_tokens=max_tokens,
            temperature=0.7,
            top_p=0.8,
            top_k=20,
            min_p=0.0,
            presence_penalty=1.5,
            stream=True,
        ))
        return response

    def _build_llm_messages(self, messages, mode: str = "chat"):
        """Build llm message list"""
        visible_messages = [m for m in messages if not m.get("hidden")]
        system_messages = [m for m in visible_messages if m.get("role") == "system"]
        non_system_messages = [m for m in visible_messages if m.get("role") != "system"]
        if CHAT_CONTEXT_KEEP_MESSAGES > 0:
            non_system_messages = non_system_messages[-CHAT_CONTEXT_KEEP_MESSAGES:]
        system_content = build_soul_system_prompt("voice" if mode == "voice" else "chat")
        if mode == "chat" and system_messages:
            extra_system = str(system_messages[0].get("content") or "").strip()
            if extra_system and extra_system not in system_content:
                system_content = f"{system_content}\n\nConversation-specific system instruction:\n{extra_system}"

        llm_messages = [{"role": "system", "content": system_content}]

        for m in non_system_messages:
            if m.get("hidden"):
                continue
            content = m["content"]
            # Always non-thinking mode
            if " /think" in content:
                content = content.replace(" /think", " /no_think")
            elif " /no_think" not in content:
                content += " /no_think"
            llm_messages.append({"role": m["role"], "content": content})

        return llm_messages

    async def stream_response_chunks(self, messages, max_tokens=128, abort_event: asyncio.Event | None = None, mode: str = "chat"):
        """Run llama.cpp streaming on a worker thread and yield chunks asynchronously."""
        llm_messages = self._build_llm_messages(messages, mode=mode)
        loop = asyncio.get_running_loop()
        chunk_queue: asyncio.Queue = asyncio.Queue()

        def produce_chunks():
            try:
                llm = self._current_llm()
                stream = llm.create_chat_completion(
                    messages=llm_messages,
                    max_tokens=max_tokens,
                    temperature=0.7,
                    top_p=0.8,
                    top_k=20,
                    min_p=0.0,
                    presence_penalty=1.5,
                    stream=True,
                )
                for chunk in stream:
                    if abort_event is not None and abort_event.is_set():
                        break
                    loop.call_soon_threadsafe(chunk_queue.put_nowait, chunk)
            except Exception as exc:
                loop.call_soon_threadsafe(chunk_queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(chunk_queue.put_nowait, _STREAM_DONE)

        threading.Thread(target=produce_chunks, daemon=True).start()

        while True:
            item = await chunk_queue.get()
            if item is _STREAM_DONE:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    async def _synthesize_to_audio_queue(self, text: str, audio_queue: asyncio.Queue, abort_event: asyncio.Event):
        loop = asyncio.get_running_loop()

        def produce_audio():
            try:
                for audio in self.tts.iter_pcm_chunks(text, abort_event=abort_event):
                    if abort_event.is_set():
                        break
                    loop.call_soon_threadsafe(audio_queue.put_nowait, audio)
            except Exception as exc:
                loop.call_soon_threadsafe(audio_queue.put_nowait, exc)

        await loop.run_in_executor(None, produce_audio)

    async def _tts_text_worker(self, text_queue: asyncio.Queue, audio_queue: asyncio.Queue, abort_event: asyncio.Event):
        while True:
            text = await text_queue.get()
            if text is None or abort_event.is_set():
                break
            await self._synthesize_to_audio_queue(text, audio_queue, abort_event)
        await audio_queue.put(_STREAM_DONE)

    async def ai_response_and_speak(self, websocket: WebSocket, text: str, abort_event: asyncio.Event, message_queue: asyncio.Queue):
        """
        Stream LLM text into clause sized Piper synthesis and stream PCM chunks
        over the voice WebSocket as soon as Piper emits them.
        """
        generation = self.voice_interrupts.begin(abort_event)
        with self._voice_state_lock:
            if self.voice_pipeline_active:
                logger.warning("Voice pipeline already active; ignoring duplicate trigger")
                self.voice_interrupts.finish(abort_event)
                return
            self.voice_pipeline_active = True
        logger.info("Triggering AI response for: %s", text)
        self._refresh_voice_system_message()
        self.voice_messages.append({"role": "user", "content": text})

        route = _get_route(text)
        logger.debug("[voice] route: %s", route)

        full_response = ""
        ws_stream_open = True
        send_lock = asyncio.Lock()
        tts_text_queue: asyncio.Queue = asyncio.Queue()
        audio_queue: asyncio.Queue = asyncio.Queue()
        tts_started = asyncio.Event()
        audio_sequence = 0
        logger.debug("[voice] pipeline start route=%s message_len=%d", route, len(text))

        async def send_json(payload: dict, context: str = "") -> bool:
            if not self.voice_interrupts.is_current(generation):
                logger.debug("Skipping stale voice websocket send for %s", context or payload.get("type"))
                return False
            async with send_lock:
                return await _safe_ws_send_json(websocket, payload, context=context)

        async def audio_sender():
            nonlocal audio_sequence, ws_stream_open
            sent_start = False
            while True:
                item = await audio_queue.get()
                if item is _STREAM_DONE:
                    if sent_start and ws_stream_open:
                        if not await send_json({"type": "tts_audio_end"}, context="tts_audio_end"):
                            ws_stream_open = False
                    return
                if isinstance(item, Exception):
                    raise item
                if abort_event.is_set():
                    continue
                if not sent_start:
                    sent_start = True
                    tts_started.set()
                    if ws_stream_open:
                        if not await send_json({"type": "voice_status", "status": "speaking"}, context="voice_status speaking audio"):
                            ws_stream_open = False
                        if ws_stream_open:
                            if not await send_json(
                                {
                                    "type": "tts_audio_start",
                                    "format": "pcm_s16le",
                                    "sample_rate": self.tts.sample_rate,
                                    "channels": 1,
                                },
                                context="tts_audio_start",
                            ):
                                ws_stream_open = False
                if ws_stream_open:
                    audio_sequence += 1
                    if not await send_json(
                        {
                            "type": "tts_audio_chunk",
                            "seq": audio_sequence,
                            "format": "pcm_s16le",
                            "sample_rate": self.tts.sample_rate,
                            "channels": 1,
                            "audio": base64.b64encode(item).decode("ascii"),
                        },
                        context="tts_audio_chunk",
                    ):
                        ws_stream_open = False

        tts_task = asyncio.create_task(self._tts_text_worker(tts_text_queue, audio_queue, abort_event))
        audio_task = asyncio.create_task(audio_sender())

        async def wait_for_tts_completion(tool_cancel_event: threading.Event | None = None) -> str | None:
            pending = {tts_task, audio_task}
            while pending:
                action = await self._consume_voice_control_messages(
                    websocket,
                    message_queue,
                    abort_event,
                    tool_cancel_event=tool_cancel_event,
                )
                if action in {"interrupt_listening", "interrupt", "disconnect", "wake_command_queued"}:
                    return action
                if abort_event.is_set():
                    return "abort"
                done, pending = await asyncio.wait(
                    pending,
                    timeout=0.05,
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in done:
                    if task.cancelled():
                        continue
                    exc = task.exception()
                    if exc is not None:
                        raise exc
            return None

        try:
            if not await send_json({"type": "ai_start"}, context="ai_start"):
                return
            if not await send_json({"type": "voice_status", "status": "thinking"}, context="voice_status thinking"):
                return

            if route == "function_gemma":
                logger.info("[voice] running function_gemma path")
                loop = asyncio.get_running_loop()
                tool_cancel_event = threading.Event()
                tool_future = loop.run_in_executor(None, _run_tool_ai_subprocess, text, tool_cancel_event)
                while not tool_future.done():
                    action = await self._consume_voice_control_messages(
                        websocket,
                        message_queue,
                        abort_event,
                        tool_cancel_event=tool_cancel_event,
                    )
                    if action in {"interrupt_listening", "interrupt", "disconnect", "wake_command_queued"}:
                        return
                    if abort_event.is_set():
                        tool_cancel_event.set()
                        break
                    await asyncio.sleep(0.05)
                if abort_event.is_set():
                    await send_json({"type": "ai_aborted"}, context="ai_aborted tool path")
                    return
                tool_call_raw, tool_result = await tool_future
                display_text = str(tool_result) if tool_result is not None else "No tool call produced."
                if tool_call_raw:
                    self.voice_messages.append({"role": "assistant", "content": tool_call_raw, "hidden": True})
                self.voice_messages.append({"role": "assistant", "content": display_text})
                self._remember_from_interaction(text, display_text, "voice")
                if len(self.voice_messages) > 6:
                    self.voice_messages = [self.voice_messages[0]] + self.voice_messages[-5:]
                if not abort_event.is_set():
                    await send_json({"type": "ai_delta", "text": display_text}, context="ai_delta tool path")
                    await send_json({"type": "ai_final", "text": display_text}, context="ai_final tool path")
                    await tts_text_queue.put(display_text)
                    await tts_text_queue.put(None)
                    action = await wait_for_tts_completion(tool_cancel_event=tool_cancel_event)
                    if action in {"interrupt_listening", "interrupt", "disconnect", "wake_command_queued"}:
                        return
                    await send_json({"type": "voice_done"}, context="voice_done tool path")
                    await send_json({"type": "voice_status", "status": "idle"}, context="voice_status idle tool path")
                return

            # qwen_basic path — always non-thinking
            logger.info("[voice] streaming response route=%s messages=%d", route, len(self.voice_messages))
            voice_max_tokens = 96
            tts_buffer = ""
            chunk_index = 0

            async for chunk in self.stream_response_chunks(self.voice_messages, max_tokens=voice_max_tokens, abort_event=abort_event, mode="voice"):
                chunk_index += 1
                action = await self._consume_voice_control_messages(websocket, message_queue, abort_event)
                if action in {"interrupt_listening", "interrupt", "disconnect", "wake_command_queued"}:
                    await tts_text_queue.put(None)
                    return

                if abort_event.is_set():
                    await send_json({"type": "ai_aborted"}, context="ai_aborted")
                    await tts_text_queue.put(None)
                    break

                choices = chunk.get("choices") or []
                if not choices:
                    continue
                content = choices[0].get("delta", {}).get("content")
                if not content:
                    continue

                full_response += content
                if chunk_index % 20 == 1:
                    logger.debug("[voice] streamed chunk=%d response_len=%d", chunk_index, len(full_response))

                clean_response = strip_think_for_ui(full_response)
                if ws_stream_open:
                    if not await send_json({"type": "ai_delta", "text": clean_response}, context="ai_delta"):
                        logger.info("Voice websocket closed during ai_delta; continuing generation and caching final reply")
                        ws_stream_open = False

                clean_chunk = strip_think_for_ui(content)
                if clean_chunk:
                    tts_buffer = f"{tts_buffer}{clean_chunk}"
                    units, tts_buffer = _pop_voice_tts_units(tts_buffer)
                    for unit in units:
                        await tts_text_queue.put(unit)

            if abort_event.is_set():
                await tts_text_queue.put(None)
                await audio_queue.put(_STREAM_DONE)
                if ws_stream_open:
                    await send_json({"type": "voice_done"}, context="voice_done aborted")
                    await send_json({"type": "voice_status", "status": "idle"}, context="voice_status idle after abort")
                return

            if not abort_event.is_set():
                clean_reply = strip_think_for_ui(full_response)
                if not clean_reply:
                    logger.warning("Voice reply contained no speakable text after think-strip; using fallback reply")
                    clean_reply = VOICE_EMPTY_REPLY_FALLBACK

                units, tts_buffer = _pop_voice_tts_units(tts_buffer, final=True)
                for unit in units:
                    await tts_text_queue.put(unit)

                memory_reply = full_response if strip_think_for_ui(full_response) else clean_reply
                self.voice_messages.append({"role": "assistant", "content": memory_reply})
                self._remember_from_interaction(text, clean_reply, "voice")
                if len(self.voice_messages) > 6:
                    self.voice_messages = [self.voice_messages[0]] + self.voice_messages[-5:]

                if ws_stream_open:
                    if not await send_json({"type": "ai_final", "text": clean_reply}, context="ai_final"):
                        ws_stream_open = False

                if not ws_stream_open:
                    self.pending_voice_reply = clean_reply
                    logger.info("Cached pending voice reply for next websocket reconnect (len=%d)", len(clean_reply))

                await tts_text_queue.put(None)
                action = await wait_for_tts_completion()
                if action in {"interrupt_listening", "interrupt", "disconnect", "wake_command_queued"}:
                    return

                if not tts_started.is_set() and ws_stream_open:
                    await send_json({"type": "voice_status", "status": "idle"}, context="voice_status idle no speech")

                if ws_stream_open:
                    await send_json({"type": "voice_done"}, context="voice_done")
                    await send_json({"type": "voice_status", "status": "idle"}, context="voice_status idle after voice_done")

        except Exception as e:
            logger.exception("Error in AI response pipeline: %s", e)
            abort_event.set()
            await send_json({"type": "error", "message": str(e)}, context="voice pipeline error")
            await send_json({"type": "voice_status", "status": "idle"}, context="voice_status idle after pipeline error")
        finally:
            if not tts_task.done():
                await tts_text_queue.put(None)
                tts_task.cancel()
            if not audio_task.done():
                await audio_queue.put(_STREAM_DONE)
                audio_task.cancel()
            for task in (tts_task, audio_task):
                if not task.done():
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
            self.voice_interrupts.finish(abort_event)
            with self._voice_state_lock:
                self.voice_pipeline_active = False
            self.resume_wake_listener()


# --- Router Initialization ---
router = APIRouter()
ai = AIState()
register_memory_duplicate_checker(ai.memory_candidate_already_stored)


def require_control_auth(
    request: Request,
    x_nova_token: str | None = Header(default=None, alias="X-NOVA-Token"),
) -> None:
    """Require the local GUI token for conversation mutations."""
    client_host = request.client.host if request.client else None
    if not is_valid_control_token(x_nova_token) and not _is_local_client(client_host):
        raise HTTPException(status_code=401, detail="Missing or invalid local GUI authorization.")


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


async def authorize_control_websocket(websocket: WebSocket) -> bool:
    """Reject unauthenticated WebSocket clients before accepting the socket."""
    token = websocket.query_params.get("token")
    client_host = websocket.client.host if websocket.client else None
    if _is_local_client(client_host) or is_valid_control_token(token):
        return True
    await websocket.close(code=1008, reason="Missing or invalid local GUI authorization")
    return False


@router.get("/conversations")
async def list_conversations():
    return ai.conv_manager.list_conversations()


class CreateConversationBody(BaseModel):
    title: Optional[str] = None
    messages: Optional[List[dict]] = None


@router.post("/conversations", dependencies=[Depends(require_control_auth)])
async def create_conversation(body: Optional[CreateConversationBody] = None):
    title = (body.title if body else None) or "New Chat"
    messages = body.messages if body and body.messages is not None else None
    return ai.conv_manager.create_conversation(title=title, messages=messages)


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = ai.conv_manager.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.patch("/conversations/{conv_id}", dependencies=[Depends(require_control_auth)])
async def rename_conversation(conv_id: str, data: dict):
    new_title = data.get("title")
    if not new_title:
        raise HTTPException(status_code=400, detail="Title is required")
    conv = ai.conv_manager.rename_conversation(conv_id, new_title)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/conversations/{conv_id}", dependencies=[Depends(require_control_auth)])
async def delete_conversation(conv_id: str):
    ai.conv_manager.delete_conversation(conv_id)
    return {"status": "success"}


@router.websocket("/ws/chat/{conv_id}")
async def chat_websocket_endpoint(websocket: WebSocket, conv_id: str):
    if not await authorize_control_websocket(websocket):
        return
    await websocket.accept()
    logger.info("Chat websocket connected for conversation %s", conv_id)

    conv = ai.conv_manager.get_conversation(conv_id)
    if not conv:
        await websocket.send_json({"type": "error", "message": "Conversation not found"})
        await websocket.close()
        return

    await websocket.send_json({
        "type": "history",
        "messages": [{"role": m["role"], "text": m["content"], "hidden": m.get("hidden", False)} for m in conv["messages"]]
    })

    abort_event = asyncio.Event()
    message_queue = asyncio.Queue()

    async def receive_messages():
        try:
            while True:
                data = await websocket.receive_json()
                await message_queue.put(data)
        except WebSocketDisconnect:
            logger.info("Chat websocket receive loop disconnected for conversation %s", conv_id)
            await message_queue.put({"type": "__disconnect__"})
        except Exception:
            logger.exception("Chat websocket receive loop failed for conversation %s", conv_id)
            await message_queue.put({"type": "__disconnect__"})

    receive_task = asyncio.create_task(receive_messages())

    try:
        while True:
            data = await message_queue.get()
            message_type = data.get("type")

            if message_type == "__disconnect__":
                logger.info("Chat websocket disconnect sentinel received for conversation %s", conv_id)
                break

            if message_type == "send":
                abort_event.clear()
                user_text = data.get("message", "")
                if not user_text:
                    continue

                conv["messages"].append({"role": "user", "content": user_text, "timestamp": time.time()})

                if len(conv["messages"]) == 1:
                    conv["title"] = user_text[:30] + ("..." if len(user_text) > 30 else "")

                ai.conv_manager.update_conversation(conv_id, conv["messages"])

                try:
                    route = _get_route(user_text)
                    logger.debug("[chat] route=%s conv_id=%s text_len=%d", route, conv_id, len(user_text))

                    await websocket.send_json({"type": "stream_start"})
                    logger.debug("[chat] stream_start sent for conversation %s", conv_id)

                    if route == "function_gemma":
                        loop = asyncio.get_event_loop()
                        logger.info("[chat] running function_gemma path for conversation %s", conv_id)
                        tool_call_raw, tool_result = await loop.run_in_executor(
                            None, _run_tool_ai_subprocess, user_text
                        )
                        display_reply = str(tool_result) if tool_result is not None else "No tool call produced."
                        if not abort_event.is_set():
                            await websocket.send_json({"type": "stream_delta", "text": display_reply})
                            await websocket.send_json({"type": "stream_final", "text": display_reply})
                            if tool_call_raw:
                                conv["messages"].append({"role": "assistant", "content": tool_call_raw, "timestamp": time.time(), "hidden": True})
                            conv["messages"].append({"role": "assistant", "content": display_reply, "timestamp": time.time()})
                            ai._remember_from_interaction(user_text, display_reply, "chat")
                            ai.conv_manager.update_conversation(conv_id, conv["messages"])
                    else:
                        # qwen_basic — always non-thinking
                        full_reply = ""
                        sent_display_text = ""
                        logger.info("[chat] generating response route=%s conv_id=%s", route, conv_id)
                        async for chunk in ai.stream_response_chunks(conv["messages"], max_tokens=2048, abort_event=abort_event):
                            while not message_queue.empty():
                                msg = await message_queue.get()
                                if msg.get("type") == "abort":
                                    abort_event.set()
                                elif msg.get("type") == "__disconnect__":
                                    abort_event.set()
                                    raise WebSocketDisconnect()

                            if abort_event.is_set():
                                await websocket.send_json({"type": "stream_aborted"})
                                break

                            delta = chunk['choices'][0]['delta']
                            if 'content' in delta:
                                content = delta['content']
                                full_reply += content
                                display_text = strip_think_for_ui(full_reply)
                                if display_text.startswith(sent_display_text):
                                    display_delta = display_text[len(sent_display_text):]
                                else:
                                    display_delta = display_text
                                if display_delta:
                                    await websocket.send_json({"type": "stream_delta", "text": display_delta})
                                sent_display_text = display_text

                            await asyncio.sleep(0.01)

                        if not abort_event.is_set():
                            display_text = strip_think_for_ui(full_reply)
                            await websocket.send_json({"type": "stream_final", "text": display_text})
                            conv["messages"].append({"role": "assistant", "content": full_reply, "timestamp": time.time()})
                            ai._remember_from_interaction(user_text, display_text, "chat")
                            ai.conv_manager.update_conversation(conv_id, conv["messages"])
                except Exception as e:
                    logger.exception("Chat send error: %s", e)
                    try:
                        await websocket.send_json({"type": "stream_error", "error": str(e)})
                    except Exception:
                        pass

            elif message_type == "abort":
                abort_event.set()

    except WebSocketDisconnect:
        logger.info("Client disconnected from conversation %s", conv_id)
    finally:
        receive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await receive_task


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    if not await authorize_control_websocket(websocket):
        return
    await websocket.accept()
    logger.info("Voice client connected")
    abort_event = asyncio.Event()
    message_queue = asyncio.Queue()
    ai.register_voice_connection(websocket, asyncio.get_running_loop(), message_queue)

    if ai.pending_voice_reply:
        replay_text = ai.pending_voice_reply
        ai.pending_voice_reply = None
        logger.info("Replaying cached voice reply after websocket reconnect (len=%d)", len(replay_text))
        await _safe_ws_send_json(websocket, {"type": "ai_final", "text": replay_text}, context="ai_final replay")
        await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "idle"}, context="voice_status idle replay")

    async def receive_messages():
        try:
            while True:
                data = await websocket.receive_json()
                await message_queue.put(data)
        except WebSocketDisconnect:
            logger.info("Voice websocket receive loop disconnected")
            await message_queue.put({"type": "__disconnect__"})
        except Exception:
            logger.exception("Voice websocket receive loop failed")
            await message_queue.put({"type": "__disconnect__"})

    receive_task = asyncio.create_task(receive_messages())

    try:
        while True:
            data = await message_queue.get()
            command = data.get("type")

            if command == "__disconnect__":
                logger.info("Voice websocket disconnect sentinel received; closing voice loop")
                break

            logger.debug("Voice command received: %s payload_keys=%s", command, sorted(list(data.keys())))

            if command in {"__wake_word__", "__wake_word_command__"}:
                command_text = str(data.get("command") or "").strip()
                if command == "__wake_word__" and ai.voice_pipeline_active:
                    ai.pause_wake_listener()
                    if command_text:
                        await ai._handle_voice_interrupt(websocket, abort_event, start_listening=False)
                        await message_queue.put({"type": "__wake_word_command__", "command": command_text})
                    else:
                        await ai._handle_voice_interrupt(websocket, abort_event, start_listening=True)
                    abort_event = asyncio.Event()
                    continue
                abort_event = asyncio.Event()
                await ai._handle_wake_word_event(
                    websocket,
                    abort_event,
                    message_queue,
                    command_text=command_text,
                )
                if abort_event.is_set():
                    abort_event = asyncio.Event()

            elif command == "start_vosk":
                logger.info("Voice start_vosk requested; current recording=%s", ai.is_vosk_recording)
                if not ai.is_vosk_recording:
                    try:
                        ai.pause_wake_listener()
                        ai.is_vosk_recording = True
                        loop = asyncio.get_event_loop()

                        async def vosk_callback(text):
                            try:
                                await _safe_ws_send_json(websocket, {"type": "vosk_partial", "text": text}, context="vosk_partial")
                            except Exception:
                                logger.exception("Voice Vosk partial callback failed")

                        logger.info("Starting Vosk listening")
                        ai.vosk.start_listening(callback=lambda t: asyncio.run_coroutine_threadsafe(vosk_callback(t), loop))
                        if not ai.vosk.listening:
                            ai.is_vosk_recording = False
                            logger.error("Vosk failed to enter listening state")
                            await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "idle"}, context="voice_status idle after vosk start failure")
                            await _safe_ws_send_json(websocket, {"type": "error", "message": "Vosk failed to start listening"}, context="vosk start failure")
                        else:
                            logger.info("Vosk listening started successfully")
                            await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "listening"}, context="voice_status listening")
                    except Exception as e:
                        ai.is_vosk_recording = False
                        logger.exception("Vosk start error: %s", e)
                        await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "idle"}, context="voice_status idle after vosk exception")
                        await _safe_ws_send_json(websocket, {"type": "error", "message": f"Vosk start error: {e}"}, context="vosk start exception")

            elif command == "stop_vosk":
                if ai.is_vosk_recording:
                    logger.info("Stopping Vosk recording")
                    ai.is_vosk_recording = False
                    text = ai.vosk.stop_listening()
                    logger.info("Vosk stop completed; text_len=%d text=%r", len(text or ""), text[:120] if text else "")
                    transcription_only = data.get("transcription_only", False)
                    if text:
                        await _safe_ws_send_json(websocket, {"type": "vosk_final", "text": text}, context="vosk_final")
                        if transcription_only:
                            logger.info("Transcription-only voice stop complete; returning to idle")
                            await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "idle"}, context="voice_status idle after transcription_only vosk")
                        else:
                            logger.info("Routing Vosk text into AI response pipeline")
                            await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "thinking"}, context="voice_status thinking after vosk")
                            ai.resume_wake_listener()
                            await ai.ai_response_and_speak(websocket, text, abort_event, message_queue)
                            if abort_event.is_set():
                                abort_event = asyncio.Event()
                    else:
                        logger.warning("Vosk stopped but produced no text")
                        await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "idle"}, context="voice_status idle after empty vosk")
                        ai.resume_wake_listener()

            elif command in {"toggle_voice", "__wake_capture_timeout__"}:
                if command == "__wake_capture_timeout__" and not ai.is_recording:
                    continue
                if not ai.is_recording:
                    logger.info("Starting Whisper capture; current recording=%s", ai.is_recording)
                    abort_event = asyncio.Event()
                    await ai._start_whisper_capture(websocket)
                else:
                    ai.is_recording = False
                    logger.info(
                        "Stopping Whisper and transcribing%s",
                        " after wake follow-up window" if command == "__wake_capture_timeout__" else "",
                    )
                    await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "transcribing"}, context="voice_status transcribing whisper stop")
                    text = await ai._stop_whisper_and_transcribe()
                    logger.info("Whisper transcription completed; text_len=%d text=%r", len(text or ""), text[:120] if text else "")
                    transcription_only = data.get("transcription_only", False)
                    if text:
                        await _safe_ws_send_json(websocket, {"type": "voice_transcription", "text": text}, context="voice_transcription")
                        if transcription_only:
                            logger.info("Transcription only whisper stop complete; returning to idle")
                            await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "idle"}, context="voice_status idle after transcription_only whisper")
                        else:
                            logger.info("Sending whisper transcript into AI response pipeline")
                            ai.resume_wake_listener()
                            await ai.ai_response_and_speak(websocket, text, abort_event, message_queue)
                            if abort_event.is_set():
                                abort_event = asyncio.Event()
                    else:
                        logger.warning("Whisper stopped but produced no text")
                        await _safe_ws_send_json(websocket, {"type": "voice_status", "status": "idle"}, context="voice_status idle after empty whisper")
                        ai.resume_wake_listener()

            elif command == "interrupt_voice":
                await ai._handle_voice_interrupt(
                    websocket,
                    abort_event,
                    start_listening=data.get("start_listening", True),
                )
                abort_event = asyncio.Event()

            elif command == "abort":
                logger.info("Global Abort Requested")
                abort_event.set()
                ai.interrupt_voice_pipeline()
                await _safe_ws_send_json(websocket, {"type": "tts_audio_cancel"}, context="tts_audio_cancel abort command")
                ai.resume_wake_listener()

            elif command == "task.list":
                try:
                    from task_scheduler import list_jobs
                    jobs = list_jobs()
                    await websocket.send_json({"type": "task_list", "jobs": jobs})
                except Exception as e:
                    logger.warning("[task.list] %s", e)
                    await websocket.send_json({"type": "task_list", "jobs": []})

            elif command == "task.add":
                try:
                    from task_scheduler import add_job
                    name = data.get("name", "").strip() or "Task"
                    description = (data.get("description") or "").strip()
                    schedule = data.get("schedule")
                    payload = data.get("payload") or {}
                    if not schedule:
                        await websocket.send_json({"type": "task_added", "result": False, "error": "Missing schedule"})
                    else:
                        job = add_job(name=name, description=description, schedule=schedule, payload=payload)
                        await websocket.send_json({"type": "task_added", "result": True, "job": job})
                except Exception as e:
                    logger.warning("[task.add] %s", e)
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({"type": "task_added", "result": False, "error": str(e)})

            elif command == "task.update":
                try:
                    from task_scheduler import update_job
                    job_id = data.get("id")
                    name = data.get("name", "").strip() or None
                    description = data.get("description")
                    if description is not None:
                        description = (description or "").strip()
                    schedule = data.get("schedule")
                    payload = data.get("payload")
                    if not job_id:
                        await websocket.send_json({"type": "task_updated", "result": False, "error": "Missing id"})
                    else:
                        job = update_job(job_id, name=name, description=description, schedule=schedule, payload=payload)
                        if job:
                            await websocket.send_json({"type": "task_updated", "result": True, "job": job})
                        else:
                            await websocket.send_json({"type": "task_updated", "result": False, "error": "Job not found"})
                except Exception as e:
                    logger.warning("[task.update] %s", e)
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({"type": "task_updated", "result": False, "error": str(e)})

            elif command == "task.remove":
                try:
                    from task_scheduler import remove_job
                    job_id = data.get("id")
                    if job_id:
                        remove_job(job_id)
                    await websocket.send_json({"type": "task_removed"})
                except Exception as e:
                    logger.warning("[task.remove] %s", e)
                    await websocket.send_json({"type": "task_removed"})

    except WebSocketDisconnect:
        logger.info("Voice client disconnected")
    except Exception as e:
        logger.exception("Voice WebSocket error: %s", e)
        import traceback
        traceback.print_exc()
    finally:
        ai.unregister_voice_connection(websocket)
        receive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await receive_task
