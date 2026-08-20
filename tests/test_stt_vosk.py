import queue

import pytest

import stt_vosk


class FakePyAudio:
    def __init__(self, *, open_error=None):
        self.open_error = open_error

    def get_default_input_device_info(self):
        return {
            "index": 4,
            "name": "Selected microphone",
            "defaultSampleRate": 48000,
        }

    def is_format_supported(self, rate, **kwargs):
        return rate == stt_vosk.RATE and kwargs["input_device"] == 4

    def open(self, **kwargs):
        if self.open_error is not None:
            raise self.open_error
        return object()


def make_engine(fake_p):
    engine = stt_vosk.STTEngine.__new__(stt_vosk.STTEngine)
    engine.model = object()
    engine.recognizer = None
    engine.listening = False
    engine.audio_queue = queue.Queue()
    engine.thread = None
    engine.stream = None
    engine.p = fake_p
    engine.final_text = ""
    engine.current_rate = stt_vosk.RATE
    engine.device_index = None
    return engine


def test_vosk_prefers_default_input_device():
    engine = make_engine(FakePyAudio())

    assert engine._get_input_device_index() == (4, stt_vosk.RATE)


def test_vosk_start_failure_does_not_leave_false_listening_state(monkeypatch):
    engine = make_engine(FakePyAudio(open_error=OSError("device busy")))
    monkeypatch.setattr(stt_vosk, "KaldiRecognizer", lambda model, rate: object())

    with pytest.raises(OSError, match="device busy"):
        engine.start_listening()

    assert engine.listening is False
    assert engine.stream is None
