import collections
import queue
import threading
import numpy as np
import time
import os
import json
from pathlib import Path

from quiet_io import silence_stderr_fd

os.environ["ORT_LOGGING_LEVEL"] = "3"
os.environ["ORT_LOG_SEVERITY_LEVEL"] = "3"
os.environ.setdefault("LONG_LOG_LEVEL", "3")

with silence_stderr_fd():
    import pyaudio
    from faster_whisper import WhisperModel

# --- CONFIGURATION ---
PROJECT_ROOT = Path(os.getenv("NOVA_PROJECT_ROOT", Path(__file__).resolve().parent)).resolve()


def _env_int(name, default):
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_optional_str(name, default=None):
    raw = os.environ.get(name, default)
    if raw is None:
        return None
    value = raw.strip()
    if not value or value.lower() in {"auto", "none", "null"}:
        return None
    return value


MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "base").strip() or "base"
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu").strip() or "cpu"
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
CPU_THREADS = _env_int("WHISPER_CPU_THREADS", min(4, os.cpu_count() or 4))
BEAM_SIZE = 1                # Greedy decoding for minimum latency
CHUNK_SIZE = 1024           # Frames per buffer
FORMAT = pyaudio.paInt16    # 16-bit PCM
CHANNELS = 1                # Mono
RATE = 16000                # Whisper expects 16kHz
SILENCE_THRESHOLD = 500     # Adjust based on your mic sensitivity
WHISPER_VOCABULARY_PATH = os.environ.get("WHISPER_VOCABULARY_PATH", "").strip()
MAX_CAPTURE_SECONDS = max(5, int(os.environ.get("WHISPER_MAX_CAPTURE_SECONDS", "45")))
LANGUAGE = _env_optional_str("WHISPER_LANGUAGE", "en")
VAD_FILTER = _env_bool("WHISPER_VAD_FILTER", True)
CONDITION_ON_PREVIOUS_TEXT = _env_bool("WHISPER_CONDITION_ON_PREVIOUS_TEXT", False)
WITHOUT_TIMESTAMPS = _env_bool("WHISPER_WITHOUT_TIMESTAMPS", True)

def _vocabulary_candidates():
    if WHISPER_VOCABULARY_PATH:
        path = Path(WHISPER_VOCABULARY_PATH).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return [path]
    return [PROJECT_ROOT / "vocabulary.txt", PROJECT_ROOT / "vocabulary.json"]
# ---------------------

class STTEngine:
    def __init__(self):
        self.model = None
        self.listening = False
        self.audio_queue = queue.Queue()
        self.result_queue = queue.Queue() # For passing text back to main thread
        self.thread = None
        self.stream = None
        with silence_stderr_fd():
            self.p = pyaudio.PyAudio()
        self.live_thread = None
        self.audio_frames = bytearray()
        self._capture_lock = threading.Lock()
        self._config_lock = threading.RLock()
        self.current_rate = RATE
        self.current_channels = CHANNELS
        self.max_capture_bytes = max(1, MAX_CAPTURE_SECONDS * RATE * CHANNELS * 2)
        self.language = LANGUAGE
        self.vad_filter = VAD_FILTER
        self.condition_on_previous_text = CONDITION_ON_PREVIOUS_TEXT
        self.without_timestamps = WITHOUT_TIMESTAMPS
        self.vocabulary = None
        self.load_vocabulary()

    def _drain_audio_queue(self):
        """Drop any queued microphone frames so the next capture starts clean."""
        try:
            while True:
                self.audio_queue.get_nowait()
        except queue.Empty:
            pass

    def _reset_capture_buffer(self):
        with self._capture_lock:
            self.audio_frames = bytearray()

    def _snapshot_capture_buffer(self):
        with self._capture_lock:
            return bytes(self.audio_frames)

    def get_config(self):
        with self._config_lock:
            return {
                "model_size": MODEL_SIZE,
                "language": self.language or "auto",
                "vad_filter": self.vad_filter,
                "condition_on_previous_text": self.condition_on_previous_text,
                "without_timestamps": self.without_timestamps,
            }

    def update_config(self, *, language=None):
        with self._config_lock:
            if language is not None:
                normalized_language = str(language or "").strip().lower()
                self.language = None if normalized_language in {"", "auto", "none", "null"} else normalized_language
            return self.get_config()

    def load_vocabulary(self):
        vocabularies = []
        for vocab_file in _vocabulary_candidates():
            if vocab_file.exists():
                try:
                    if vocab_file.suffix == ".txt":
                        with vocab_file.open("r", encoding="utf-8") as f:
                            words = [line.strip() for line in f if line.strip()]
                        vocabularies.append(" ".join(words))
                    elif vocab_file.suffix == ".json":
                        with vocab_file.open("r", encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, list):
                            vocabularies.append(" ".join(data))
                        elif isinstance(data, dict) and "vocab" in data:
                            vocabularies.append(" ".join(data["vocab"]))
                        else:
                            print(f"Unsupported vocabulary.json format in {vocab_file}")
                            continue
                    else:
                        print(f"Unsupported vocabulary file extension in {vocab_file}")
                        continue
                    print(f"Loaded vocabulary from {vocab_file}")
                except Exception as e:
                    print(f"Error loading vocabulary from {vocab_file}: {e}")
                    continue
        if vocabularies:
            self.vocabulary = " ".join(vocabularies)
        else:
            print("No vocabulary file found. Set WHISPER_VOCABULARY_PATH or add vocabulary.txt/json to the project root.")

    def load_model(self):
        if self.model is None:
            print(f"Loading Whisper model '{MODEL_SIZE}'...")
            with silence_stderr_fd():
                self.model = WhisperModel(
                    MODEL_SIZE,
                    device=DEVICE,
                    compute_type=COMPUTE_TYPE,
                    cpu_threads=CPU_THREADS,
                )
            print("Whisper model loaded.")

    def _mic_callback(self, in_data, frame_count, time_info, status):
        if self.listening:
            self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def start_listening(self):
        if self.listening:
            return

        device_index = self._get_input_device_index()
        if device_index is None:
            print("Error: No input device found.")
            return
        
        # Ensure model is loaded (this might block if not preloaded, so best to preload)
        if not self.model:
            self.load_model()
            
        self.listening = True
        self.audio_queue = queue.Queue() # Clear queue
        
        self.stream = self.p.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        input_device_index=device_index,
                        frames_per_buffer=CHUNK_SIZE,
                        stream_callback=self._mic_callback)
        
        self.thread = threading.Thread(target=self._process_audio, daemon=True)
        self.thread.start()
        print("STT Started Listening")

    def stop_listening(self):
        self.listening = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        # We don't join the thread immediately to avoid UI blocking, it will exit loop
        print("STT Stopped Listening")

    def _process_audio(self):
        # Buffer to hold current "phrase"
        MAX_BUFFER_LEN = 100 # ~3 seconds of audio
        audio_buffer = collections.deque(maxlen=MAX_BUFFER_LEN)
        
        while self.listening:
            try:
                # Get data from queue with timeout to allow checking self.listening
                data = self.audio_queue.get(timeout=0.5)
                audio_buffer.append(data)
                
                # Drain pending
                while not self.audio_queue.empty():
                    audio_buffer.append(self.audio_queue.get())

                # Transcribe if we have enough data? 
                # Actually, for a "Push to Talk" style, we might want to just accumulate 
                # and transcribe ONLY when stopped or periodically?
                # The user request said: "start to transcribe my voice then when I press it again it stops transcription then that transcription is sent"
                # This implies we should ACCUMULATE audio while listening, and transcribe AT THE END.
                
                # However, for long sentences, intermediate transcription is nice.
                # But for simplicity and satisfying "sent to ai model... when I press it again it stops",
                # let's just keep accumulating in a larger buffer?
                # If we use deque with maxlen, we lose start.
                # Let's switch to a list for the full session if it's push-to-talk.
                # Wait, if I speak for 10 seconds, deque(100) (approx 3s) will lose info.
                
                # REVISION: creating a full buffer for the session.
                pass 
            except queue.Empty:
                continue
        
        # End of listening loop - Final Transcription
        if len(audio_buffer) > 0:
            full_audio = b''.join(audio_buffer)
            # We need to preserve ALL audio for the final query? 
            # The existing code used a deque for rolling window.
            # But the user interaction model is "Press Start -> Speak -> Press Stop -> Transcribe".
            # So I should probably capture EVERYTHING between Start and Stop.
        else:
            return

    def transcribe_accumulated(self):
        """
        Actually, let's change the strategy.
        _mic_callback fills a buffer.
        When stop_listening is called, we process that buffer.
        """
        pass # Re-implementing logic below

    # RETHINKING IMPLEMENTATION FOR USER REQUEST:
    # "press it, it start to transcribe... press it again it stops... then that transcription is sent"
    
    def _get_input_device_index(self):
        """Find the best available input device that supports our target rate, or any rate."""
        default_index = None
        try:
            default_dev = self.p.get_default_input_device_info()
            default_index = int(default_dev.get('index'))
            if self.p.is_format_supported(
                RATE,
                input_device=default_index,
                input_channels=CHANNELS,
                input_format=FORMAT,
            ):
                print(f"Using default device {default_index}: {default_dev.get('name')} (Supports {RATE}Hz)")
                return default_index
        except Exception:
            pass

        # If the default cannot capture at 16000Hz, find another compatible input.
        for i in range(self.p.get_device_count()):
            dev = self.p.get_device_info_by_index(i)
            if dev.get('maxInputChannels') > 0:
                try:
                    if self.p.is_format_supported(RATE, input_device=i, input_channels=CHANNELS, input_format=FORMAT):
                        print(f"Using device {i}: {dev.get('name')} (Supports {RATE}Hz)")
                        return i
                except:
                    continue
        
        if default_index is not None:
            print(f"Falling back to default device {default_index}")
            return default_index

        # Last resort: just find any input device
        for i in range(self.p.get_device_count()):
            dev = self.p.get_device_info_by_index(i)
            if dev.get('maxInputChannels') > 0:
                print(f"Falling back to device {i}: {dev.get('name')}")
                return i
                
        return None

    def start_capture(self):
        if self.listening: return
        
        device_index = self._get_input_device_index()
        if device_index is None:
            print("Error: No input device found.")
            return

        # Whisper needs exactly 16000Hz and Mono
        self.current_rate = RATE
        self.current_channels = CHANNELS
        
        print(f"Opening stream for Whisper: {self.current_rate}Hz, {self.current_channels} channels")

        self.listening = True
        self._reset_capture_buffer()
        self._drain_audio_queue()
        
        if not self.model: self.load_model()

        try:
            self.stream = self.p.open(format=FORMAT,
                            channels=self.current_channels,
                            rate=self.current_rate,
                            input=True,
                            input_device_index=device_index,
                            frames_per_buffer=CHUNK_SIZE,
                            stream_callback=self._capture_callback)
        except Exception as e:
            print(f"Failed to open PyAudio stream natively at {self.current_rate}Hz: {e}")
            self.listening = False
            return
        print("Capture Started")

    def _capture_callback(self, in_data, frame_count, time_info, status):
        if self.listening:
            with self._capture_lock:
                remaining = self.max_capture_bytes - len(self.audio_frames)
                if remaining > 0:
                    self.audio_frames.extend(in_data[:remaining])
                if remaining <= len(in_data):
                    self.listening = False
        return (None, pyaudio.paContinue)

    def stop_and_transcribe(self):
        self.listening = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        
        audio_bytes = self._snapshot_capture_buffer()
        frame_count = len(audio_bytes) // (CHUNK_SIZE * CHANNELS * 2)
        print(f"Capture Stopped. Frames: {frame_count}")
        if not audio_bytes:
            self._reset_capture_buffer()
            self._drain_audio_queue()
            return ""
        
        # Process
        try:
            return self._transcribe_buffer(audio_bytes)
        finally:
            self._reset_capture_buffer()
            self._drain_audio_queue()

    def _transcribe_buffer(self, audio_bytes):
        start_t = time.time()
        
        # We now capture exactly at 16000Hz, 1 channel so we don't need expensive resampling.
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        with self._config_lock:
            language = self.language
            vad_filter = self.vad_filter
            condition_on_previous_text = self.condition_on_previous_text
            without_timestamps = self.without_timestamps
        
        # Transcribe with vocabulary if available
        kwargs = {
            "beam_size": BEAM_SIZE,
            "best_of": 1,
            "temperature": 0.0,
            "vad_filter": vad_filter,
            "condition_on_previous_text": condition_on_previous_text,
            "without_timestamps": without_timestamps,
        }
        if language:
            kwargs["language"] = language
        if self.vocabulary:
            kwargs["initial_prompt"] = self.vocabulary
        
        segments, _ = self.model.transcribe(audio_np, **kwargs)
        
        text = " ".join([s.text for s in segments]).strip()
        print(f"Transcription ({time.time()-start_t:.2f}s): {text}")
        return text

    def terminate(self):
        self.listening = False
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                print(f"Whisper stream cleanup warning: {e}")
            finally:
                self.stream = None
        self._reset_capture_buffer()
        self._drain_audio_queue()
        self.p.terminate()


if __name__ == "__main__":
    # Test
    engine = STTEngine()
    engine.load_model()
    try:
        while True:
            input("Press Enter to Start Recording...")
            engine.start_capture()
            input("Press Enter to Stop and Transcribe...")
            text = engine.stop_and_transcribe()
            print(f"Final Text: {text}")
    except KeyboardInterrupt:
        engine.terminate()
