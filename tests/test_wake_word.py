from wake_word import WakeWordDetector, match_wake_word, normalize_wake_phrases


def test_wake_word_extracts_direct_command():
    match = match_wake_word("Hey Nova, what time is it?")

    assert match is not None
    assert match.phrase == "hey nova"
    assert match.command == "what time is it"


def test_wake_word_accepts_swedish_variant_without_command():
    match = match_wake_word("hej nova")

    assert match is not None
    assert match.phrase == "hej nova"
    assert match.command == ""


def test_wake_word_accepts_nova_alone():
    match = match_wake_word("nova")

    assert match is not None
    assert match.phrase == "nova"
    assert match.command == ""


def test_wake_word_accepts_vosk_noah_variant():
    match = match_wake_word("hey noah what time is it")

    assert match is not None
    assert match.phrase == "hey noah"
    assert match.command == "what time is it"


def test_wake_word_ignores_unrelated_speech():
    assert match_wake_word("what time is it") is None


def test_wake_word_detector_waits_for_stable_partial_and_debounces():
    now = [100.0]
    detector = WakeWordDetector(clock=lambda: now[0], partial_stability_seconds=0.4)

    assert detector.detect("hey nova", is_partial=True) is None
    now[0] = 100.2
    assert detector.detect("hey nova", is_partial=True) is None
    now[0] = 100.5
    assert detector.detect("hey nova", is_partial=True) is None
    assert detector.detect("hey nova", is_partial=False) is not None

    now[0] = 102.0
    assert detector.detect("hey nova what time", is_partial=True) is None
    now[0] = 102.5
    assert detector.detect("hey nova what time", is_partial=True).command == "what time"


def test_wake_word_detector_final_result_triggers_immediately():
    detector = WakeWordDetector()

    assert detector.detect("hej nova", is_partial=False) is not None


def test_wake_phrase_normalization_accepts_comma_separated_string():
    assert normalize_wake_phrases("Hey Nova, Hej Nova") == ["hey nova", "hej nova"]
