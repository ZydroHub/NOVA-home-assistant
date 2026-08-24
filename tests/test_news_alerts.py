"""Tests for shared Swedish alert normalization and deduping."""
import pytest


@pytest.fixture(autouse=True)
def clear_alert_caches(monkeypatch):
    import news_alerts

    monkeypatch.setattr(news_alerts, "_schedule_alert_severity_background", lambda **kwargs: None)

    with news_alerts._SWEDISH_ALERTS_CACHE_LOCK:
        news_alerts._SWEDISH_ALERTS_CACHE.clear()
    with news_alerts._ALERT_SEVERITY_CACHE_LOCK:
        news_alerts._ALERT_SEVERITY_CACHE.clear()
        news_alerts._ALERT_SEVERITY_PENDING.clear()
    news_alerts.register_alert_severity_classifier(None)
    yield
    with news_alerts._SWEDISH_ALERTS_CACHE_LOCK:
        news_alerts._SWEDISH_ALERTS_CACHE.clear()
    with news_alerts._ALERT_SEVERITY_CACHE_LOCK:
        news_alerts._ALERT_SEVERITY_CACHE.clear()
        news_alerts._ALERT_SEVERITY_PENDING.clear()
    news_alerts.register_alert_severity_classifier(None)


def test_normalize_alert_item_sets_canonical_fields():
    from news_alerts import normalize_alert_item

    item = normalize_alert_item(
        {
            "source": "Polisen",
            "title": "Traffic stop",
            "summary": "Road blocked",
            "published": "2026-04-27T10:00:00Z",
            "location": "Nacka",
            "url": "https://example.invalid/alert",
            "priority_rank": 80,
            "priority_label": "Police",
        },
        region="nacka",
    )

    assert item["id"]
    assert item["title"] == "Traffic stop"
    assert item["description"] == "Road blocked"
    assert item["priority"] == "Police"
    assert item["type"] == "Polisen"
    assert item["timestamp"] == "2026-04-27T10:00:00Z"
    assert item["region"] == "nacka"


def test_polisen_ai_severity_accepts_extreme(monkeypatch):
    import news_alerts

    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", lambda **kwargs: "EXTREME")

    rank, label = news_alerts.polisen_ai_severity(title="Terror attack", summary="Many injured")

    assert rank == 100
    assert label == "EXTREME"


def test_polisen_ai_severity_falls_back_for_unknown_model_output(monkeypatch):
    import news_alerts

    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", lambda **kwargs: "Police")

    rank, label = news_alerts.polisen_ai_severity(title="Traffic stop", summary="Routine check")

    assert rank == 50
    assert label == "MEDIUM"


def test_polisen_ai_severity_forces_routine_events_low(monkeypatch):
    import news_alerts

    def fail_if_called(**kwargs):
        raise AssertionError("routine guard should run before the AI model")

    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", fail_if_called)

    rank, label = news_alerts.polisen_ai_severity(
        title="22 augusti 07.21, Trafikkontroll, Sigtuna",
        summary="En trafikkontroll har genomförts under morgonen.",
    )

    assert rank == 25
    assert label == "LOW"


def test_polisen_ai_severity_forces_minor_fraud_low(monkeypatch):
    import news_alerts

    def fail_if_called(**kwargs):
        raise AssertionError("minor fraud guard should run before the AI model")

    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", fail_if_called)

    rank, label = news_alerts.polisen_ai_severity(
        title="18 augusti 15.25, Bedrageri, Stockholm",
        summary="En man forsokte ga in pa ett gym olovligt.",
    )

    assert (rank, label) == (25, "LOW")


def test_polisen_ai_severity_downgrades_extreme_without_extreme_signals(monkeypatch):
    import news_alerts

    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", lambda **kwargs: "EXTREME")

    rank, label = news_alerts.polisen_ai_severity(
        title="Misshandel",
        summary="En person har skadats.",
    )

    assert rank == 75
    assert label == "HIGH"


def test_polisen_ai_severity_cache_reuses_classification(monkeypatch):
    import news_alerts

    calls = []

    def fake_classifier(**kwargs):
        calls.append(kwargs)
        return "LOW"

    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", fake_classifier)

    first = news_alerts.polisen_ai_severity(title="Brand", published="2026-04-27T10:00:00Z")
    second = news_alerts.polisen_ai_severity(title="Brand", published="2026-04-27T10:00:00Z")

    assert first == (25, "LOW")
    assert second == (25, "LOW")
    assert len(calls) == 1


def test_polisen_ai_severity_uses_registered_classifier(monkeypatch):
    import news_alerts

    calls = []

    def registered_classifier(title, summary, location, published):
        calls.append((title, summary, location, published))
        return "HIGH"

    def fail_loader(**kwargs):
        raise AssertionError("fallback loader should not be used")

    news_alerts.register_polisen_severity_classifier(registered_classifier)
    monkeypatch.setattr(news_alerts, "_get_alert_severity_llm", fail_loader)

    rank, label = news_alerts.polisen_ai_severity(
        title="Brand",
        summary="Stor insats",
        location="Stockholm",
        published="",
    )

    assert (rank, label) == (75, "HIGH")
    assert calls == [("Brand", "Stor insats", "Stockholm", "")]


def test_alert_ai_severity_can_return_fallback_and_schedule_background(monkeypatch):
    import news_alerts

    scheduled = []

    def fake_schedule(**kwargs):
        scheduled.append(kwargs)

    def fail_if_called(**kwargs):
        raise AssertionError("AI classifier should not block when wait_for_ai=False")

    monkeypatch.setattr(news_alerts, "_schedule_alert_severity_background", fake_schedule)
    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", fail_if_called)

    rank, label = news_alerts.alert_ai_severity(
        source="SOS Alarm",
        title="Brand i byggnad",
        location="Stockholm",
        wait_for_ai=False,
    )

    assert (rank, label) == (50, "MEDIUM")
    assert len(scheduled) == 1
    assert scheduled[0]["source"] == "SOS Alarm"


def test_fetch_swedish_alerts_deduplicates_by_source_and_title(monkeypatch):
    import news_alerts

    def fake_fetch_json(url, timeout=8.0):
        if "polisen.se/api/events" in url:
            return [
                {
                    "name": "Duplicate event",
                    "summary": "First copy",
                    "datetime": "2026-04-27T10:00:00Z",
                    "location": "Stockholm",
                    "url": "https://example.invalid/1",
                },
                {
                    "name": "Duplicate event",
                    "summary": "Second copy",
                    "datetime": "2026-04-27T10:05:00Z",
                    "location": "Stockholm",
                    "url": "https://example.invalid/2",
                },
            ]
        if "krisinformation.se" in url:
            return {}
        if "henrikhjelm.se" in url:
            return {}
        return {}

    monkeypatch.setattr(news_alerts, "fetch_json", fake_fetch_json)

    result = news_alerts.fetch_swedish_alerts(limit=12, region="stockholm")

    assert result["region"] == "stockholm"
    assert result["count"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["title"] == "Duplicate event"


def test_fetch_swedish_alerts_schedules_ai_severity_for_polisen_without_blocking(monkeypatch):
    import news_alerts

    def fake_fetch_json(url, timeout=8.0):
        if "polisen.se/api/events" in url:
            return [
                {
                    "name": "Trafikolycka",
                    "summary": "Flera fordon inblandade",
                    "datetime": "2026-08-22T10:00:00Z",
                    "location": "Stockholm",
                    "url": "https://example.invalid/polisen",
                }
            ]
        if "krisinformation.se" in url:
            return {}
        if "henrikhjelm.se" in url:
            return {}
        return {}

    monkeypatch.setattr(news_alerts, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", lambda **kwargs: "HIGH")
    scheduled = []
    monkeypatch.setattr(news_alerts, "_schedule_alert_severity_background", lambda **kwargs: scheduled.append(kwargs))

    result = news_alerts.fetch_swedish_alerts(limit=12, region="stockholm")

    assert result["items"][0]["source"] == "Polisen"
    assert result["items"][0]["priority_label"] == "MEDIUM"
    assert result["items"][0]["priority"] == "MEDIUM"
    assert result["items"][0]["priority_rank"] == 50
    assert scheduled[0]["source"] == "Polisen"


def test_fetch_swedish_alerts_can_disable_polisen_ai_severity(monkeypatch):
    import news_alerts

    def fake_fetch_json(url, timeout=8.0):
        if "polisen.se/api/events" in url:
            return [
                {
                    "name": "Trafikolycka",
                    "summary": "Flera fordon inblandade",
                    "datetime": "2026-08-22T10:00:00Z",
                    "location": "Stockholm",
                    "url": "https://example.invalid/polisen",
                }
            ]
        if "krisinformation.se" in url:
            return {}
        if "henrikhjelm.se" in url:
            return {}
        return {}

    scheduled = []
    monkeypatch.setattr(news_alerts, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(news_alerts, "_schedule_alert_severity_background", lambda **kwargs: scheduled.append(kwargs))

    result = news_alerts.fetch_swedish_alerts(limit=12, region="stockholm", police_ai_severity=False)

    assert result["items"][0]["source"] == "Polisen"
    assert result["items"][0]["priority_label"] == ""
    assert result["items"][0]["priority"] == ""
    assert result["items"][0]["priority_rank"] == 0
    assert scheduled == []


def test_fetch_swedish_alerts_uses_ai_severity_for_non_polisen_sources(monkeypatch):
    import news_alerts

    def fake_fetch_json(url, timeout=8.0):
        if "polisen.se/api/events" in url:
            return []
        if "vmas" in url:
            return {
                "vmas": [
                        {
                            "Headline": "Viktigt meddelande",
                            "Area": "Stockholm",
                            "Published": "",
                            "Link": "https://example.invalid/vma",
                        }
                ]
            }
        if "news" in url:
            return {"news": []}
        if "henrikhjelm.se" in url:
            return {}
        return {}

    monkeypatch.setattr(news_alerts, "fetch_json", fake_fetch_json)

    result = news_alerts.fetch_swedish_alerts(limit=12, region="stockholm")

    assert result["items"][0]["source"] == "Krisinformation VMA"
    assert result["items"][0]["priority_label"] == "EXTREME"
    assert result["items"][0]["priority_rank"] == 100


def test_krisinformation_area_object_list_is_displayed_as_text(monkeypatch):
    import news_alerts

    def fake_fetch_json(url, timeout=8.0):
        if "polisen.se/api/events" in url:
            return []
        if "vmas" in url:
            return {"vmas": []}
        if "news" in url:
            return {
                "news": [
                    {
                        "Headline": "Skoldadet pa Brinellskolan i Fagersta",
                        "Area": [{"Type": "Country", "Description": "Sverige", "GeometryInformation": None}],
                        "Published": "2026-08-22T10:00:00Z",
                        "Link": "https://example.invalid/kris",
                    }
                ]
            }
        if "henrikhjelm.se" in url:
            return {}
        return {}

    monkeypatch.setattr(news_alerts, "fetch_json", fake_fetch_json)

    result = news_alerts.fetch_swedish_alerts(limit=12, region="nacka")

    assert result["items"][0]["location"] == "Sverige"
    assert result["items"][0]["description"] == "Sverige"


def test_krisinformation_floor_keeps_important_alerts_high(monkeypatch):
    import news_alerts

    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", lambda **kwargs: "LOW")

    rank, label = news_alerts.alert_ai_severity(
        source="Krisinformation",
        title="Driftstorning",
        summary="Stockholm",
    )

    assert (rank, label) == (75, "HIGH")


def test_school_attack_is_extreme_without_model_call(monkeypatch):
    import news_alerts

    def fail_if_called(**kwargs):
        raise AssertionError("school attack guard should run before the AI model")

    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", fail_if_called)

    rank, label = news_alerts.alert_ai_severity(
        source="Krisinformation",
        title="Skolattack vid Brinellskolan i Fagersta",
        summary="Viktigt meddelande till allmanheten",
    )

    assert (rank, label) == (100, "EXTREME")


def test_sos_alarm_uses_ai_severity(monkeypatch):
    import news_alerts

    calls = []

    def fake_classifier(**kwargs):
        calls.append(kwargs)
        return "HIGH"

    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", fake_classifier)

    rank, label = news_alerts.alert_ai_severity(
        source="SOS Alarm",
        title="Brand i byggnad",
        location="Stockholm",
    )

    assert (rank, label) == (75, "HIGH")
    assert calls[0]["source"] == "SOS Alarm"


def test_krisinformation_sorts_before_polisen_at_same_rank(monkeypatch):
    import news_alerts

    def fake_fetch_json(url, timeout=8.0):
        if "polisen.se/api/events" in url:
            return [
                {
                    "name": "Stor polisinsats",
                    "summary": "Flera patruller pa plats",
                    "datetime": "2026-08-22T10:00:00Z",
                    "location": "Stockholm",
                    "url": "https://example.invalid/polisen",
                }
            ]
        if "vmas" in url:
            return {"vmas": []}
        if "news" in url:
            return {
                "news": [
                    {
                        "Headline": "Krisinformation Stockholm",
                        "Area": "Stockholm",
                        "Published": "2026-08-22T09:00:00Z",
                        "Link": "https://example.invalid/kris",
                    }
                ]
            }
        if "henrikhjelm.se" in url:
            return {}
        return {}

    monkeypatch.setattr(news_alerts, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", lambda **kwargs: "HIGH")

    result = news_alerts.fetch_swedish_alerts(limit=12, region="stockholm")

    assert [item["source"] for item in result["items"][:2]] == ["Krisinformation", "Polisen"]


def test_extreme_vma_bypasses_local_region_filter(monkeypatch):
    import news_alerts

    def fake_fetch_json(url, timeout=8.0):
        if "polisen.se/api/events" in url:
            return []
        if "vmas" in url:
            return {
                "vmas": [
                    {
                        "Headline": "Viktigt meddelande till allmanheten",
                        "Area": "Fagersta",
                        "Published": "2026-08-22T10:00:00Z",
                        "Link": "https://example.invalid/vma-fagersta",
                    }
                ]
            }
        if "news" in url:
            return {"news": []}
        if "henrikhjelm.se" in url:
            return {}
        return {}

    monkeypatch.setattr(news_alerts, "fetch_json", fake_fetch_json)

    result = news_alerts.fetch_swedish_alerts(limit=12, region="nacka")

    assert result["items"][0]["source"] == "Krisinformation VMA"
    assert result["items"][0]["location"] == "Fagersta"
    assert result["items"][0]["priority_label"] == "EXTREME"


def test_global_extreme_alerts_can_be_limited_to_matching_region(monkeypatch):
    import news_alerts

    def fake_fetch_json(url, timeout=8.0):
        if "polisen.se/api/events" in url:
            return []
        if "vmas" in url:
            return {
                "vmas": [
                    {
                        "Headline": "Viktigt meddelande till allmanheten",
                        "Area": "Fagersta",
                        "Published": "2026-08-22T10:00:00Z",
                        "Link": "https://example.invalid/vma-fagersta",
                    }
                ]
            }
        if "news" in url:
            return {"news": []}
        if "henrikhjelm.se" in url:
            return {}
        return {}

    monkeypatch.setattr(news_alerts, "fetch_json", fake_fetch_json)

    local_result = news_alerts.fetch_swedish_alerts(limit=12, region="nacka", global_extreme_alerts=False)
    sweden_result = news_alerts.fetch_swedish_alerts(limit=12, region="sweden", global_extreme_alerts=False)

    assert local_result["items"] == []
    assert sweden_result["items"][0]["priority_label"] == "EXTREME"


def test_extreme_school_attack_bypasses_local_region_filter(monkeypatch):
    import news_alerts

    def fake_fetch_json(url, timeout=8.0):
        if "polisen.se/api/events" in url:
            return []
        if "vmas" in url:
            return {"vmas": []}
        if "news" in url:
            return {
                "news": [
                    {
                        "Headline": "Skolattack vid Brinellskolan",
                        "Area": "Fagersta",
                        "Published": "2026-08-22T10:00:00Z",
                        "Link": "https://example.invalid/school",
                    }
                ]
            }
        if "henrikhjelm.se" in url:
            return {}
        return {}

    monkeypatch.setattr(news_alerts, "fetch_json", fake_fetch_json)

    result = news_alerts.fetch_swedish_alerts(limit=12, region="stockholm")

    assert result["items"][0]["source"] == "Krisinformation"
    assert result["items"][0]["location"] == "Fagersta"
    assert result["items"][0]["priority_label"] == "EXTREME"


def test_non_extreme_outside_region_stays_filtered(monkeypatch):
    import news_alerts

    def fake_fetch_json(url, timeout=8.0):
        if "polisen.se/api/events" in url:
            return []
        if "vmas" in url:
            return {"vmas": []}
        if "news" in url:
            return {
                "news": [
                    {
                        "Headline": "Driftstorning",
                        "Area": "Fagersta",
                        "Published": "2026-08-22T10:00:00Z",
                        "Link": "https://example.invalid/non-extreme",
                    }
                ]
            }
        if "henrikhjelm.se" in url:
            return {}
        return {}

    monkeypatch.setattr(news_alerts, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(news_alerts, "_classify_alert_severity_with_ai", lambda **kwargs: "HIGH")

    result = news_alerts.fetch_swedish_alerts(limit=12, region="stockholm")

    assert result["items"] == []
