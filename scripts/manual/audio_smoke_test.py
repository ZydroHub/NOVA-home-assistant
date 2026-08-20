import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

import stt_whisper
try:
    engine = stt_whisper.STTEngine()
    engine.start_capture()
    print("Whisper start_capture returned successfully")
    engine.stop_and_transcribe()
except Exception as e:
    print(f"Whisper Exception: {e}")

import stt_vosk
try:
    engine_v = stt_vosk.STTEngine()
    engine_v.start_listening()
    print("Vosk start_listening returned successfully")
    engine_v.stop_listening()
except Exception as e:
    print(f"Vosk Exception: {e}")
