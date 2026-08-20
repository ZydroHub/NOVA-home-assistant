import queue
import threading
import sys
import json
import os

from quiet_io import silence_stderr_fd, silence_stdio_fd

os.environ["VOSK_LOG_LEVEL"] = "0"
os.environ["KALDI_LOG_LEVEL"] = "0"

with silence_stdio_fd():
    import pyaudio
    from vosk import Model, KaldiRecognizer

# --- CONFIGURATION ---
PROJECT_ROOT = os.getenv("NOVA_PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL_PATH = os.path.join(PROJECT_ROOT, "models", "vosk", "vosk-model-small-en-us-0.15")
MODEL_PATH = os.getenv("VOSK_MODEL_PATH", DEFAULT_MODEL_PATH)
CHUNK_SIZE = 4000           # Frames per buffer
FORMAT = pyaudio.paInt16    # 16-bit PCM
CHANNELS = 1                # Mono
RATE = 16000                # Vosk standard sample rate
import numpy as np
try:
    import scipy.signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ---------------------

class STTEngine:
    def __init__(self):
        self.model = None
        self.recognizer = None
        self.listening = False
        self.audio_queue = queue.Queue()
        self.thread = None
        self.stream = None
        with silence_stdio_fd():
            self.p = pyaudio.PyAudio()
        self.final_text = ""
        self.current_rate = RATE
        self.device_index = None

    def load_model(self):
        if self.model is None:
            print(f"Loading Vosk model from '{MODEL_PATH}'...")
            try:
                with silence_stdio_fd():
                    self.model = Model(MODEL_PATH)
                    self.recognizer = KaldiRecognizer(self.model, RATE)
                print("Vosk model loaded successfully.")
            except Exception as e:
                print(f"\nError loading model: {e}")
                print("---")
                print(f"Please double-check that this exact path contains the model files (like 'am', 'conf', 'graph', etc.):")
                print(MODEL_PATH)
                raise RuntimeError(f"Vosk model could not be loaded from {MODEL_PATH}") from e

    def _get_input_device_index(self):
        """Find the best available input device that supports our target rate, or any rate."""
        # Prefer the user's default microphone. Device 0 is often an HDMI or
        # monitor input even when another microphone is selected system-wide.
        try:
            default_dev = self.p.get_default_input_device_info()
            idx = int(default_dev.get('index'))
            rate = int(default_dev.get('defaultSampleRate') or RATE)
            try:
                if self.p.is_format_supported(RATE, input_device=idx, input_channels=CHANNELS, input_format=FORMAT):
                    print(f"Using default device {idx}: {default_dev.get('name')} (Supports {RATE}Hz)")
                    return idx, RATE
            except Exception:
                pass
            print(f"Using default device {idx}: {default_dev.get('name')} (Default rate: {rate}Hz)")
            return idx, rate
        except Exception:
            pass

        # If no default is available, find an input that supports 16000Hz.
        for i in range(self.p.get_device_count()):
            dev = self.p.get_device_info_by_index(i)
            if dev.get('maxInputChannels') > 0:
                try:
                    if self.p.is_format_supported(RATE, input_device=i, input_channels=CHANNELS, input_format=FORMAT):
                        print(f"Using device {i}: {dev.get('name')} (Supports {RATE}Hz)")
                        return i, RATE
                except:
                    continue
        
        # Last resort: just find any input device
        for i in range(self.p.get_device_count()):
            dev = self.p.get_device_info_by_index(i)
            if dev.get('maxInputChannels') > 0:
                rate = int(dev.get('defaultSampleRate'))
                print(f"Falling back to device {i}: {dev.get('name')} (Rate: {rate}Hz)")
                return i, rate
                
        return None, None

    def _mic_callback(self, in_data, frame_count, time_info, status):
        """Puts live audio frames into a queue for the background thread."""
        if self.listening:
            self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def start_listening(self, callback=None):
        if self.listening: 
            return
        
        if not self.model: 
            self.load_model()
            
        self.device_index, self.current_rate = self._get_input_device_index()
        if self.device_index is None:
            print("Error: No input device found.")
            return

        self.callback = callback
        self.audio_queue = queue.Queue() # Clear the queue
        self.final_text = ""
        with silence_stdio_fd():
            self.recognizer = KaldiRecognizer(self.model, RATE)

        print(f"Opening Vosk stream: {self.current_rate}Hz, {CHANNELS} channels")
        try:
            self.stream = self.p.open(format=FORMAT,
                            channels=CHANNELS,
                            rate=self.current_rate,
                            input=True,
                            input_device_index=self.device_index,
                            frames_per_buffer=CHUNK_SIZE,
                            stream_callback=self._mic_callback)
        except Exception:
            self.listening = False
            self.stream = None
            raise

        self.listening = True
        self.thread = threading.Thread(target=self._process_audio, daemon=True)
        self.thread.start()

    def stop_listening(self):
        self.listening = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        
        if self.thread:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                print("Warning: Vosk audio processing thread did not stop within 2s.")
            else:
                self.thread = None
        
        return self.final_text

    def _process_audio(self):
        """Background loop that continuously passes the audio queue to Vosk."""
        accumulated_text = []

        while self.listening or not self.audio_queue.empty():
            try:
                data = self.audio_queue.get(timeout=0.1)
                
                # Resample if necessary
                if self.current_rate != RATE:
                    audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    if HAS_SCIPY:
                        num_samples = int(len(audio_np) * RATE / self.current_rate)
                        audio_np = scipy.signal.resample(audio_np, num_samples)
                    else:
                        # Simple linear interpolation fallback if scipy is missing
                        from scipy import interpolate
                        x_old = np.linspace(0, 1, len(audio_np))
                        x_new = np.linspace(0, 1, int(len(audio_np) * RATE / self.current_rate))
                        f = interpolate.interp1d(x_old, audio_np)
                        audio_np = f(x_new)
                    data = audio_np.astype(np.int16).tobytes()

                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "")
                    if text:
                        accumulated_text.append(text)
                        if self.callback:
                            full = ' '.join(accumulated_text)
                            try:
                                self.callback(full, is_partial=False)
                            except TypeError:
                                self.callback(full)
                
                else:
                    partial_result = json.loads(self.recognizer.PartialResult())
                    partial_text = partial_result.get("partial", "")
                    if partial_text:
                        current_live = ' '.join(accumulated_text + [partial_text])
                        if self.callback:
                            try:
                                self.callback(current_live, is_partial=True)
                            except TypeError:
                                self.callback(current_live)

            except queue.Empty:
                pass

        # Flush any remaining audio in the buffer when stopped
        final_result = json.loads(self.recognizer.FinalResult())
        final_text = final_result.get("text", "")
        if final_text:
            accumulated_text.append(final_text)

        self.final_text = ' '.join(accumulated_text).strip()
        if self.callback:
            try:
                self.callback(self.final_text, is_partial=False)
            except TypeError:
                self.callback(self.final_text)

    def terminate(self):
        self.p.terminate()

if __name__ == "__main__":
    def _print_transcript(text, is_partial=False):
        """Print transcription in real time; partial overwrites the line, final prints newline."""
        end = "\r" if is_partial else "\n"
        print(text, end=end, flush=True)

    engine = STTEngine()
    try:
        engine.load_model()
        while True:
            input("\nPress Enter to Start Recording...")
            engine.start_listening(callback=_print_transcript)
            print("Listening... (Press Enter to stop)")
            input()
            final_text = engine.stop_listening()
            print(f"--- Captured: {final_text} ---")
    except KeyboardInterrupt:
        engine.terminate()
