"""Tests for Telegram alert command handling and alert dispatch."""
import json


def test_telegram_command_subscribe_and_test(tmp_path):
    from alert_settings import AlertSettingsStore
    from telegram_bot import TelegramAlertBot

    sent_messages = []

    def fake_sender(chat_id, text):
        sent_messages.append((chat_id, text))
        return True

    bot = TelegramAlertBot(
        token="token",
        subscriptions_file=str(tmp_path / "subs.json"),
        seen_alerts_file=str(tmp_path / "seen.json"),
        settings_store=AlertSettingsStore(defaults={"nacka": False, "stockholm": False}, persist=False),
        alert_fetcher=lambda limit, region: {"items": []},
        send_message_fn=fake_sender,
        poll_interval_seconds=15,
        request_timeout_seconds=3,
    )

    assert bot.process_message(42, "/Nacka") == "Nacka alerts enabled."
    assert bot.process_message(42, "/Nacka") == "Nacka alerts disabled."
    assert bot.process_message(42, "/test") == "NOVA check-in: live, awake, and ready."
    assert sent_messages[0] == (42, "Nacka alerts enabled.")
    assert sent_messages[1] == (42, "Nacka alerts disabled.")
    assert sent_messages[2] == (42, "NOVA check-in: live, awake, and ready.")


def test_telegram_commands_toggle_regions_independently(tmp_path):
    from alert_settings import AlertSettingsStore
    from telegram_bot import TelegramAlertBot

    sent_messages = []

    def fake_sender(chat_id, text):
        sent_messages.append((chat_id, text))
        return True

    bot = TelegramAlertBot(
        token="token",
        subscriptions_file=str(tmp_path / "subs.json"),
        seen_alerts_file=str(tmp_path / "seen.json"),
        settings_store=AlertSettingsStore(defaults={"nacka": True, "stockholm": False}, persist=False),
        alert_fetcher=lambda limit, region: {"items": []},
        send_message_fn=fake_sender,
        poll_interval_seconds=15,
        request_timeout_seconds=3,
    )

    assert bot.process_message(42, "/stockholm") == "Stockholm alerts enabled."
    assert bot.process_message(42, "/Nacka") == "Nacka alerts disabled."
    assert bot.alert_settings_payload() == {"nacka": False, "stockholm": True}
    assert sent_messages == [
        (42, "Stockholm alerts enabled."),
        (42, "Nacka alerts disabled."),
    ]


def test_telegram_dispatch_primes_then_deduplicates_alerts(tmp_path):
    from telegram_bot import TelegramAlertBot

    sent_messages = []
    fetch_count = 0

    def fake_sender(chat_id, text):
        sent_messages.append((chat_id, text))
        return True

    def fake_alert_fetcher(limit, region):
        nonlocal fetch_count
        fetch_count += 1
        alert_id = "alert-1" if fetch_count == 1 else "alert-2"
        title = "Old road closure" if fetch_count == 1 else "Road closure"
        return {
            "items": [
                {
                    "id": f"{region}:{alert_id}",
                    "title": title,
                    "description": "Detour in place",
                    "priority": "Traffic",
                    "type": "Traffic",
                    "timestamp": "2026-04-27T10:00:00Z",
                    "location": "Nacka",
                    "url": "https://example.invalid/alert",
                }
            ]
        }

    bot = TelegramAlertBot(
        token="token",
        subscriptions_file=str(tmp_path / "subs.json"),
        seen_alerts_file=str(tmp_path / "seen.json"),
        alert_fetcher=fake_alert_fetcher,
        send_message_fn=fake_sender,
        poll_interval_seconds=15,
        request_timeout_seconds=3,
    )

    bot.subscribe(42, "nacka")
    bot._poll_alerts_once()
    bot._poll_alerts_once()
    bot._poll_alerts_once()

    alert_messages = [message for message in sent_messages if message[1].startswith("Traffic | Road closure")]
    assert len(alert_messages) == 1


def test_telegram_dispatch_skips_disabled_region(tmp_path):
    from telegram_bot import TelegramAlertBot

    sent_messages = []
    fetch_calls = []

    def fake_sender(chat_id, text):
        sent_messages.append((chat_id, text))
        return True

    def fake_alert_fetcher(limit, region):
        fetch_calls.append(region)
        return {
            "items": [
                {
                    "id": f"{region}:alert-1",
                    "title": f"{region} alert",
                    "description": "Test alert",
                    "priority": "News",
                    "type": "Alert",
                    "timestamp": "2026-04-27T10:00:00Z",
                    "location": region,
                    "url": "https://example.invalid/alert",
                }
            ]
        }

    bot = TelegramAlertBot(
        token="token",
        subscriptions_file=str(tmp_path / "subs.json"),
        seen_alerts_file=str(tmp_path / "seen.json"),
        nacka_enabled=True,
        stockholm_enabled=False,
        alert_fetcher=fake_alert_fetcher,
        send_message_fn=fake_sender,
        poll_interval_seconds=15,
        request_timeout_seconds=3,
    )

    bot.subscribe(42, "nacka")
    bot.subscribe(99, "stockholm")
    bot._poll_alerts_once()

    assert fetch_calls == ["nacka"]
    assert sent_messages == []


def test_telegram_broadcast_skips_disabled_subscribers(tmp_path):
    from telegram_bot import TelegramAlertBot

    sent_messages = []

    def fake_sender(chat_id, text):
        sent_messages.append((chat_id, text))
        return True

    bot = TelegramAlertBot(
        token="token",
        subscriptions_file=str(tmp_path / "subs.json"),
        seen_alerts_file=str(tmp_path / "seen.json"),
        nacka_enabled=True,
        stockholm_enabled=False,
        alert_fetcher=lambda limit, region: {"items": []},
        send_message_fn=fake_sender,
        poll_interval_seconds=15,
        request_timeout_seconds=3,
    )

    bot.subscribe(42, "nacka")
    bot.subscribe(99, "stockholm")

    sent_count = bot.send_startup_notification()

    assert sent_count == 1
    assert sent_messages == [(42, "NOVA is online. Alert radar is active.")]


def test_telegram_startup_notification_broadcasts_to_subscribers(tmp_path):
    from telegram_bot import TelegramAlertBot

    sent_messages = []

    def fake_sender(chat_id, text):
        sent_messages.append((chat_id, text))
        return True

    bot = TelegramAlertBot(
        token="token",
        subscriptions_file=str(tmp_path / "subs.json"),
        seen_alerts_file=str(tmp_path / "seen.json"),
        alert_fetcher=lambda limit, region: {"items": []},
        send_message_fn=fake_sender,
        poll_interval_seconds=15,
        request_timeout_seconds=3,
    )

    bot.subscribe(42, "nacka")
    bot.subscribe(99, "stockholm")

    sent_count = bot.send_startup_notification()

    assert sent_count == 2
    assert sent_messages == [
        (42, "NOVA is online. Alert radar is active."),
        (99, "NOVA is online. Alert radar is active."),
    ]


def test_telegram_startup_notification_can_be_disabled(tmp_path):
    from alert_settings import AlertSettingsStore
    from telegram_bot import TelegramAlertBot

    sent_messages = []

    def fake_sender(chat_id, text):
        sent_messages.append((chat_id, text))
        return True

    settings_store = AlertSettingsStore(persist=False)
    settings_store.set_startup_notifications(False)
    bot = TelegramAlertBot(
        token="token",
        subscriptions_file=str(tmp_path / "subs.json"),
        seen_alerts_file=str(tmp_path / "seen.json"),
        settings_store=settings_store,
        alert_fetcher=lambda limit, region: {"items": []},
        send_message_fn=fake_sender,
        poll_interval_seconds=15,
        request_timeout_seconds=3,
    )

    bot.subscribe(42, "nacka")

    sent_count = bot.send_startup_notification()

    assert sent_count == 0
    assert sent_messages == []


def test_telegram_test_notification_reports_missing_subscribers(tmp_path):
    from telegram_bot import TelegramAlertBot

    sent_messages = []

    def fake_sender(chat_id, text):
        sent_messages.append((chat_id, text))
        return True

    bot = TelegramAlertBot(
        token="token",
        subscriptions_file=str(tmp_path / "subs.json"),
        seen_alerts_file=str(tmp_path / "seen.json"),
        alert_fetcher=lambda limit, region: {"items": []},
        send_message_fn=fake_sender,
        poll_interval_seconds=15,
        request_timeout_seconds=3,
    )

    result = bot.send_test_notification()

    assert result["sent"] == 0
    assert result["errors"]
    assert sent_messages == []


def test_telegram_seen_alerts_persist_across_instances(tmp_path):
    from telegram_bot import TelegramAlertBot

    sent_messages = []

    def fake_sender(chat_id, text):
        sent_messages.append((chat_id, text))
        return True

    alert_payload = {
        "items": [
            {
                "id": "alert-1",
                "title": "Same alert",
                "description": "First pass",
                "priority": "News",
                "type": "Alert",
                "timestamp": "2026-04-27T10:00:00Z",
                "location": "Nacka",
                "url": "https://example.invalid/alert",
            }
        ]
    }

    subscriptions_file = str(tmp_path / "subs.json")
    bot_one = TelegramAlertBot(
        token="token",
        subscriptions_file=subscriptions_file,
        seen_alerts_file=str(tmp_path / "seen.json"),
        alert_fetcher=lambda limit, region: alert_payload,
        send_message_fn=fake_sender,
        poll_interval_seconds=15,
        request_timeout_seconds=3,
    )
    bot_one.subscribe(42, "nacka")
    bot_one._poll_alerts_once()
    with (tmp_path / "seen.json").open("r", encoding="utf-8") as handle:
        assert "alert-1" in json.load(handle)

    bot_two = TelegramAlertBot(
        token="token",
        subscriptions_file=subscriptions_file,
        seen_alerts_file=str(tmp_path / "seen.json"),
        alert_fetcher=lambda limit, region: alert_payload,
        send_message_fn=fake_sender,
        poll_interval_seconds=15,
        request_timeout_seconds=3,
    )
    bot_two.subscribe(42, "nacka")
    bot_two._poll_alerts_once()

    alert_messages = [message for message in sent_messages if message[1].startswith("News | Same alert")]
    assert len(alert_messages) == 0
