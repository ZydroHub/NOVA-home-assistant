import tool_ai


def test_music_command_phrases_are_routed_deterministically():
    assert tool_ai._match_builtin_command("play music") == "play_music"
    assert tool_ai._match_builtin_command("nova turn off the music") == "pause_music"
    assert tool_ai._match_builtin_command("nova lower the volume") == "lower_music_volume"
    assert tool_ai._match_builtin_command("nova lower the volume by 20 percent") == "lower_music_volume"
    assert tool_ai._match_builtin_command("nova sank volymen med 20 procent") == "lower_music_volume"
    assert tool_ai._match_builtin_command("nova sank med 20 procent") == "lower_music_volume"
    assert tool_ai._match_builtin_command("nova raise the volume by 10 percent") == "raise_music_volume"
    assert tool_ai._match_builtin_command("nova +10%") == "raise_music_volume"
    assert tool_ai._match_builtin_command("nova hoj med 10 procent") == "raise_music_volume"
    assert tool_ai._match_builtin_command("starta musiken") == "play_music"
    assert tool_ai._match_builtin_command("sätt på Spotify") == "play_music"
    assert tool_ai._match_builtin_command("whats the music right now that im playing") == "get_current_music"
    assert tool_ai._match_builtin_command("vilken låt spelas") == "get_current_music"


def test_current_music_reports_when_nothing_is_playing(monkeypatch):
    monkeypatch.setattr(
        tool_ai,
        "_local_api_json",
        lambda path, **kwargs: {
            "spotify_connected": True,
            "is_playing": False,
            "title": "",
            "artist": "",
        },
    )

    assert tool_ai.run_get_current_music({}) == "No music is playing right now."


def test_current_music_reports_paused_track(monkeypatch):
    monkeypatch.setattr(
        tool_ai,
        "_local_api_json",
        lambda path, **kwargs: {
            "spotify_connected": True,
            "is_playing": False,
            "title": "Midnight City",
            "artist": "M83",
        },
    )

    assert tool_ai.run_get_current_music({}) == "No music is playing right now. Midnight City by M83 is paused."


def test_current_music_reports_playing_track(monkeypatch):
    monkeypatch.setattr(
        tool_ai,
        "_local_api_json",
        lambda path, **kwargs: {
            "spotify_connected": True,
            "is_playing": True,
            "title": "Midnight City",
            "artist": "M83",
        },
    )

    assert tool_ai.run_get_current_music({}) == "You are listening to Midnight City by M83."


def test_play_music_reports_started_track(monkeypatch):
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return {"is_playing": True, "title": "Midnight City", "artist": "M83"}

    monkeypatch.setattr(tool_ai, "_local_api_json", fake_api)

    assert tool_ai.run_play_music({}) == "Playing Midnight City by M83."
    assert calls == [("/nova/spotify/play", {"method": "POST"})]


def test_pause_music_reports_paused_track(monkeypatch):
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return {"is_playing": False, "title": "Midnight City", "artist": "M83"}

    monkeypatch.setattr(tool_ai, "_local_api_json", fake_api)

    assert tool_ai.run_pause_music({}) == "Paused Midnight City by M83."
    assert calls == [("/nova/spotify/pause", {"method": "POST"})]


def test_lower_music_volume_reports_new_volume(monkeypatch):
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return {"volume_percent": 42}

    monkeypatch.setattr(tool_ai, "_local_api_json", fake_api)

    assert tool_ai.run_lower_music_volume({}) == "Spotify volume lowered to 42%."
    assert calls == [("/nova/spotify/volume?delta=-10", {"method": "POST"})]


def test_lower_music_volume_uses_requested_percent(monkeypatch):
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return {"volume_percent": 48}

    monkeypatch.setattr(tool_ai, "_local_api_json", fake_api)

    tool_call, result = tool_ai.run_task_for_backend("nova lower the volume by 20 percent")

    assert tool_call == "<start_function_call>call:lower_music_volume{percent:20}<end_function_call>"
    assert result == "Spotify volume lowered to 48%."
    assert calls == [("/nova/spotify/volume?delta=-20", {"method": "POST"})]


def test_lower_music_volume_uses_requested_swedish_percent(monkeypatch):
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return {"volume_percent": 48}

    monkeypatch.setattr(tool_ai, "_local_api_json", fake_api)

    tool_call, result = tool_ai.run_task_for_backend("nova sank volymen med 20 procent")

    assert tool_call == "<start_function_call>call:lower_music_volume{percent:20}<end_function_call>"
    assert result == "Spotify volume lowered to 48%."
    assert calls == [("/nova/spotify/volume?delta=-20", {"method": "POST"})]


def test_lower_music_volume_uses_short_swedish_requested_percent(monkeypatch):
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return {"volume_percent": 48}

    monkeypatch.setattr(tool_ai, "_local_api_json", fake_api)

    tool_call, result = tool_ai.run_task_for_backend("nova sank med 20 procent")

    assert tool_call == "<start_function_call>call:lower_music_volume{percent:20}<end_function_call>"
    assert result == "Spotify volume lowered to 48%."
    assert calls == [("/nova/spotify/volume?delta=-20", {"method": "POST"})]


def test_raise_music_volume_reports_new_volume(monkeypatch):
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return {"volume_percent": 52}

    monkeypatch.setattr(tool_ai, "_local_api_json", fake_api)

    assert tool_ai.run_raise_music_volume({}) == "Spotify volume raised to 52%."
    assert calls == [("/nova/spotify/volume?delta=10", {"method": "POST"})]


def test_raise_music_volume_uses_requested_percent(monkeypatch):
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return {"volume_percent": 58}

    monkeypatch.setattr(tool_ai, "_local_api_json", fake_api)

    tool_call, result = tool_ai.run_task_for_backend("nova raise the volume by 10 percent")

    assert tool_call == "<start_function_call>call:raise_music_volume{percent:10}<end_function_call>"
    assert result == "Spotify volume raised to 58%."
    assert calls == [("/nova/spotify/volume?delta=10", {"method": "POST"})]


def test_raise_music_volume_uses_plus_percent(monkeypatch):
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return {"volume_percent": 58}

    monkeypatch.setattr(tool_ai, "_local_api_json", fake_api)

    tool_call, result = tool_ai.run_task_for_backend("nova +10%")

    assert tool_call == "<start_function_call>call:raise_music_volume{percent:10}<end_function_call>"
    assert result == "Spotify volume raised to 58%."
    assert calls == [("/nova/spotify/volume?delta=10", {"method": "POST"})]


def test_raise_music_volume_uses_short_swedish_requested_percent(monkeypatch):
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return {"volume_percent": 58}

    monkeypatch.setattr(tool_ai, "_local_api_json", fake_api)

    tool_call, result = tool_ai.run_task_for_backend("nova hoj med 10 procent")

    assert tool_call == "<start_function_call>call:raise_music_volume{percent:10}<end_function_call>"
    assert result == "Spotify volume raised to 58%."
    assert calls == [("/nova/spotify/volume?delta=10", {"method": "POST"})]
