#!/usr/bin/env python3
"""
NOVA voice loop: STT -> semantic router -> Qwen or Function Gemma -> TTS.

- Press Enter to use Whisper for speech-to-text.
- Press V then Enter to use Vosk for speech-to-text (lighter, faster).
Your speech is routed: qwen_basic/qwen_thinking (Qwen reply) or function_gemma (tool run).
The reply or tool result is spoken via Piper TTS.

Run from project root: python scripts/manual/voice_pipeline_smoke_test.py
"""
import sys
import threading

# Ensure we can import from project
if __name__ == "__main__":
    import os
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)

from stt_whisper import STTEngine as WhisperEngine
from stt_vosk import STTEngine as VoskEngine
from tts_piper import PocketAudio
from semantic_router_ai import get_route, _generate_sync, _strip_think, _get_llm


def run_voice_loop():
    print("Loading semantic router...")
    get_route("warmup")
    print("Loading Qwen 3...")
    _get_llm()
    print("Loading TTS (Piper)...")
    tts = PocketAudio()
    print("Loading STT engines (Whisper + Vosk)...")
    whisper = WhisperEngine()
    vosk = VoskEngine()
    whisper.load_model()
    # Vosk loads on first start_listening

    print("\nReady. Each turn: choose STT, then speak.")
    print("  Enter      = use Whisper (better accuracy)")
    print("  V + Enter  = use Vosk (faster, lighter)\n")

    while True:
        try:
            choice = input("Press Enter (Whisper) or V+Enter (Vosk), then Enter to continue: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        use_vosk = choice == "v"
        stt_name = "Vosk" if use_vosk else "Whisper"

        if use_vosk:
            input("Press Enter to start listening (Vosk)... ")
            transcript = []
            def on_vosk(text, is_partial=False):
                end = "\r" if is_partial else "\n"
                print(text, end=end, flush=True)
            try:
                vosk.start_listening(callback=on_vosk)
            except Exception as e:
                print(f"Vosk start error: {e}")
                continue
            input("Press Enter to stop and send... ")
            text = vosk.stop_listening()
        else:
            input("Press Enter to start recording (Whisper)... ")
            try:
                whisper.start_capture()
            except Exception as e:
                print(f"Whisper start error: {e}")
                continue
            input("Press Enter to stop and transcribe... ")
            text = whisper.stop_and_transcribe()

        text = (text or "").strip()
        if not text:
            print("No speech detected. Try again.\n")
            continue

        print(f"\nYou [{stt_name}]: {text}")
        route = get_route(text)
        print(f"  -> route: {route}")

        if route == "function_gemma":
            print("Running tool (Function Gemma)...")
            try:
                import tool_ai
                tool_call_raw, tool_result = tool_ai.run_task_for_backend(text)
                tts_text = str(tool_result).strip() if tool_result is not None else "No tool call produced."
                if not tts_text:
                    tts_text = "No tool call produced."
                print(f"Tool result: {tts_text}")
            except Exception as e:
                tts_text = f"Tool error: {e}"
                print(tts_text)
        else:
            print("AI: ", end="", flush=True)
            raw_response = _generate_sync(text, thinking=(route == "qwen_thinking"))
            tts_text = _strip_think(raw_response)
            if not tts_text.strip():
                tts_text = "I have nothing to say."

        done = threading.Event()
        tts.set_queue_drained_callback(lambda: done.set())
        tts.speak(tts_text)
        done.wait(timeout=60)
        print()

    print("Bye.")


if __name__ == "__main__":
    run_voice_loop()
