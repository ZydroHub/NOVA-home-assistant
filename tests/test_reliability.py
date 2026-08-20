"""Regression tests for long-running reliability failure modes."""
import asyncio
import io
import queue
import threading

import pytest

import task_scheduler
from chat_ai import AIState, ConversationManager, VoiceInterruptController, _ToolAIWorker
from tts_piper import PocketAudio


def test_conversation_manager_ignores_corrupt_storage(tmp_path):
    storage = tmp_path / "conversations.json"
    storage.write_text("{not valid json", encoding="utf-8")

    manager = ConversationManager(str(storage))

    assert manager.list_conversations() == []


def test_task_scheduler_ignores_corrupt_jobs_file(tmp_path, monkeypatch):
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(task_scheduler, "JOBS_FILE", str(jobs_file))

    assert task_scheduler.list_jobs() == []


def test_task_scheduler_shutdown_clears_global_scheduler(monkeypatch):
    class FakeScheduler:
        def __init__(self):
            self.shutdown_calls = []

        def shutdown(self, wait=False):
            self.shutdown_calls.append(wait)

    scheduler = FakeScheduler()
    monkeypatch.setattr(task_scheduler, "_scheduler", scheduler)

    task_scheduler.shutdown_scheduler(wait=False)

    assert scheduler.shutdown_calls == [False]
    assert task_scheduler._scheduler is None


def test_tool_worker_stop_reaps_running_process():
    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO()
            self.terminated = False
            self.killed = False
            self.wait_calls = []

        def poll(self):
            return None if not self.terminated and not self.killed else 0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            return 0

    worker = _ToolAIWorker()
    proc = FakeProc()
    worker._proc = proc

    worker.stop()

    assert worker._proc is None
    assert proc.terminated is True
    assert proc.killed is False
    assert proc.wait_calls == [3]


def test_voice_interrupt_controller_cancels_active_generation():
    controller = VoiceInterruptController()
    abort_event = asyncio.Event()

    generation = controller.begin(abort_event)

    assert controller.is_current(generation)
    controller.interrupt()

    assert abort_event.is_set()
    assert not controller.is_current(generation)
    controller.finish(abort_event)


def test_voice_interrupt_message_cancels_tts_and_starts_listening():
    class FakeWebSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    class FakeTts:
        sample_rate = 22050

        def __init__(self):
            self.cleared = False
            self.interrupted = False

        def clear_queue(self):
            self.cleared = True

        def interrupt(self):
            self.interrupted = True

    class FakeStt:
        listening = False

        def __init__(self):
            self.started = False

        def start_capture(self):
            self.started = True
            self.listening = True

    async def run_case():
        state = AIState()
        state.tts = FakeTts()
        state.stt = FakeStt()
        websocket = FakeWebSocket()
        message_queue = asyncio.Queue()
        await message_queue.put({"type": "interrupt_voice", "start_listening": True})
        abort_event = asyncio.Event()

        result = await state._consume_voice_control_messages(websocket, message_queue, abort_event)

        return state, websocket, abort_event, result

    state, websocket, abort_event, result = asyncio.run(run_case())

    assert result == "interrupt_listening"
    assert abort_event.is_set()
    assert state.tts.cleared is True
    assert state.tts.interrupted is True
    assert state.stt.started is True
    assert state.is_recording is True
    assert [message["type"] for message in websocket.messages] == [
        "tts_audio_cancel",
        "ai_aborted",
        "voice_status",
    ]
    assert websocket.messages[-1]["status"] == "listening"


def test_wake_word_without_command_starts_timed_whisper_capture(monkeypatch):
    import chat_ai

    monkeypatch.setattr(chat_ai, "WAKE_FOLLOWUP_CAPTURE_SECONDS", 0.01)

    class FakeWebSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    class FakeStt:
        listening = False

        def start_capture(self):
            self.listening = True

    async def run_case():
        state = AIState()
        state.stt = FakeStt()
        websocket = FakeWebSocket()
        message_queue = asyncio.Queue()
        result = await state._handle_wake_word_event(
            websocket,
            asyncio.Event(),
            message_queue,
            command_text="",
        )
        timeout_message = await asyncio.wait_for(message_queue.get(), timeout=0.2)
        return state, websocket, result, timeout_message

    state, websocket, result, timeout_message = asyncio.run(run_case())

    assert result == "wake_listening"
    assert state.is_recording is True
    assert websocket.messages == [{"type": "voice_status", "status": "listening"}]
    assert timeout_message == {"type": "__wake_capture_timeout__"}


def test_disabling_always_listening_stops_and_blocks_wake_listener():
    class FakeWakeVosk:
        listening = True

        def __init__(self):
            self.stop_calls = 0

        def stop_listening(self):
            self.stop_calls += 1
            self.listening = False

    state = AIState()
    state._wake_vosk = FakeWakeVosk()

    runtime = state.apply_voice_settings({
        "language": "en",
        "always_listening": False,
        "wake_phrases": ["nova"],
        "wake_command_mode": "direct_or_listen",
    })

    assert state._wake_vosk.stop_calls == 1
    assert state.resume_wake_listener() is False
    assert runtime["wake_listener"] == "disabled"


def test_queued_wake_word_is_ignored_after_always_listening_is_disabled():
    class FakeWebSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    async def run_case():
        state = AIState()
        state.apply_voice_settings({
            "language": "en",
            "always_listening": False,
            "wake_phrases": ["nova"],
            "wake_command_mode": "direct_or_listen",
        })
        websocket = FakeWebSocket()
        result = await state._handle_wake_word_event(
            websocket,
            asyncio.Event(),
            asyncio.Queue(),
            command_text="what time is it",
        )
        return state, websocket, result

    state, websocket, result = asyncio.run(run_case())

    assert result == "wake_disabled"
    assert state.is_recording is False
    assert websocket.messages == []


def test_wake_word_during_active_voice_queues_direct_command_and_interrupts():
    class FakeWebSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    class FakeTts:
        def __init__(self):
            self.cleared = False
            self.interrupted = False

        def clear_queue(self):
            self.cleared = True

        def interrupt(self):
            self.interrupted = True

    async def run_case():
        state = AIState()
        state.tts = FakeTts()
        websocket = FakeWebSocket()
        message_queue = asyncio.Queue()
        await message_queue.put({"type": "__wake_word__", "command": "what time is it"})
        abort_event = asyncio.Event()

        result = await state._consume_voice_control_messages(websocket, message_queue, abort_event)
        queued = await message_queue.get()
        return state, websocket, abort_event, result, queued

    state, websocket, abort_event, result, queued = asyncio.run(run_case())

    assert result == "wake_command_queued"
    assert abort_event.is_set()
    assert state.tts.cleared is True
    assert state.tts.interrupted is True
    assert queued == {"type": "__wake_word_command__", "command": "what time is it"}
    assert [message["type"] for message in websocket.messages] == [
        "tts_audio_cancel",
        "ai_aborted",
        "voice_status",
    ]
    assert websocket.messages[-1]["status"] == "idle"


def test_piper_interrupt_generation_keeps_old_playback_cancelled():
    audio = PocketAudio.__new__(PocketAudio)
    audio._interrupt_event = threading.Event()
    audio._interrupt_lock = threading.Lock()
    audio._interrupt_generation = 0
    audio._drain_lock = threading.Lock()
    audio._drain_timer = None
    audio._queue = queue.Queue()

    old_generation = audio._new_playback_generation()
    audio.interrupt()
    new_generation = audio._new_playback_generation()

    assert audio._playback_interrupted(old_generation) is True
    assert audio._playback_interrupted(new_generation) is False
