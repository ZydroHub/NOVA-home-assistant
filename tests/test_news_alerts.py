"""Tests for shared Swedish alert normalization and deduping."""


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