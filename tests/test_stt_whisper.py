import stt_whisper


class FakePyAudio:
    def get_default_input_device_info(self):
        return {
            "index": 14,
            "name": "default",
            "maxInputChannels": 1,
        }

    def is_format_supported(self, rate, **kwargs):
        return rate == stt_whisper.RATE and kwargs["input_device"] == 14

    def get_device_count(self):
        return 15

    def get_device_info_by_index(self, index):
        return {
            "index": index,
            "name": "sysdefault" if index == 6 else f"device-{index}",
            "maxInputChannels": 1,
        }


def test_whisper_prefers_default_input_device_over_first_compatible_device():
    engine = stt_whisper.STTEngine.__new__(stt_whisper.STTEngine)
    engine.p = FakePyAudio()

    assert engine._get_input_device_index() == 14
