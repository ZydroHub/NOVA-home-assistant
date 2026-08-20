import tool_ai


def test_music_command_phrases_are_routed_deterministically():
    assert tool_ai._match_builtin_command("play music") == "play_music"
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
