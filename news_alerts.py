"""Shared Swedish alert fetcher and normalizer for the backend and Telegram bot."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_SWEDISH_ALERTS_CACHE_LOCK = threading.Lock()
_SWEDISH_ALERTS_CACHE: dict[str, dict[str, object]] = {}


def fetch_json(url: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "NOVA/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _fetch_json_safely(source_name: str, url: str, timeout: float = 8.0) -> dict | list | None:
    try:
        payload = fetch_json(url, timeout=timeout)
        if not isinstance(payload, (dict, list)):
            logger.warning("news_alerts: %s feed temporarily unavailable.", source_name)
            return None
        return payload
    except (TypeError, ValueError, KeyError, json.JSONDecodeError, urllib.error.HTTPError, urllib.error.URLError, UnicodeDecodeError):
        logger.warning("news_alerts: %s feed temporarily unavailable.", source_name)
        return None
    except Exception:
        logger.warning("news_alerts: %s feed temporarily unavailable.", source_name)
        return None


def normalize_alert_region(region: str) -> str:
    value = (region or "").strip().lower()
    if value in {"nacka", "stockholm", "sweden"}:
        return value
    return "nacka"


def alert_priority(source: str, title: str = "") -> tuple[int, str]:
    source_l = source.lower()
    title_l = title.lower()
    if "vma" in source_l:
        return 100, "Critical"
    if "polisen" in source_l:
        return 80, "Police"
    if "sos" in source_l:
        return 70, "Emergency"
    if "krisinformation" in source_l:
        if any(word in title_l for word in ["varning", "störning", "brand", "explosion", "olycka", "farlig"]):
            return 90, "Alert"
        return 60, "Notice"
    return 20, "News"


def region_keywords(region: str) -> tuple[str, ...]:
    if region == "nacka":
        return (
            "nacka",
            "saltsjöbaden",
            "saltsjobaden",
            "fisksätra",
            "fisksatra",
            "orminge",
            "boo",
            "saltsjö-boo",
            "saltsjo-boo",
        )
    if region == "stockholm":
        return (
            "stockholm",
            "stockholms",
            "södertälje",
            "sodertalje",
            "solna",
            "sundbyberg",
            "huddinge",
            "botkyrka",
            "haninge",
            "täby",
            "taby",
            "nacka",
            "järfälla",
            "jarfalla",
        )
    return ()


def match_region_text(region: str, *parts: str) -> bool:
    if region == "sweden":
        return True

    haystack = " ".join((part or "") for part in parts).lower()
    keywords = region_keywords(region)
    return any(keyword in haystack for keyword in keywords)


def polisen_location_name(entry: dict) -> str:
    location = entry.get("location")
    if isinstance(location, dict):
        return str(location.get("name") or "").strip()
    if isinstance(location, str):
        return location.strip()
    return ""


def parse_published_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None

    iso_candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def is_within_last_days(value: str, days: int = 30) -> bool:
    parsed = parse_published_datetime(value)
    if parsed is None:
        return True

    now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
    return parsed >= (now - timedelta(days=days))


def published_sort_value(value: str) -> float:
    parsed = parse_published_datetime(value)
    if parsed is None:
        return float("-inf")
    try:
        return parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return float("-inf")


def balance_items_by_source(items: list[dict]) -> list[dict]:
    """Interleave sources so one feed does not dominate the Sweden list."""
    if not items:
        return items

    preferred_order = [
        "Krisinformation VMA",
        "SOS Alarm",
        "Polisen",
        "Krisinformation",
    ]

    buckets: dict[str, list[dict]] = {}
    for item in items:
        source = str(item.get("source") or "Unknown")
        buckets.setdefault(source, []).append(item)

    ordered_sources = [source for source in preferred_order if source in buckets]
    ordered_sources.extend(source for source in buckets.keys() if source not in ordered_sources)

    balanced: list[dict] = []
    while True:
        added = False
        for source in ordered_sources:
            bucket = buckets.get(source) or []
            if not bucket:
                continue
            balanced.append(bucket.pop(0))
            added = True
        if not added:
            break

    return balanced


def extract_sos_statistics(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}

    def _canonicalize_stats(source: dict) -> dict[str, str]:
        aliases: dict[str, tuple[str, ...]] = {
            "Alla samtal": ("alla samtal",),
            "Polisen": ("polisen",),
            "Vårdbehov": ("vårdbehov", "vÃ¥rdbehov", "vardbehov"),
            "Räddning": ("räddning", "rÃ¤ddning", "raddning"),
            "Ej akuta behov": ("ej akuta behov",),
        }

        normalized: dict[str, str] = {
            str(k).strip().lower(): str(v)
            for k, v in source.items()
            if k is not None and v is not None
        }

        result: dict[str, str] = {}
        for canonical, keys in aliases.items():
            for key in keys:
                if key in normalized:
                    result[canonical] = normalized[key]
                    break
        return result

    for key in ["statistics", "statistik", "stats", "summary"]:
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            canonical = _canonicalize_stats(candidate)
            if canonical:
                return canonical

    return _canonicalize_stats(payload)


def build_alert_id(item: dict, region: str | None = None) -> str:
    raw_id = str(item.get("id") or item.get("alert_id") or "").strip()
    if raw_id:
        return raw_id

    source = str(item.get("source") or item.get("type") or "alert").strip().lower()
    title = str(item.get("title") or "").strip().lower()
    description = str(item.get("description") or "").strip().lower()
    timestamp = str(item.get("timestamp") or item.get("published") or "").strip().lower()
    location = str(item.get("location") or "").strip().lower()
    url = str(item.get("url") or "").strip().lower()
    seed = "|".join([source, title, description, timestamp, location, url])
    digest = hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()
    return f"{source or 'alert'}:{digest}"


def normalize_alert_item(item: dict, *, region: str, fallback_source: str = "Alert") -> dict:
    source = str(item.get("source") or fallback_source).strip() or fallback_source
    title = str(item.get("title") or item.get("Headline") or item.get("headline") or item.get("name") or "Untitled alert").strip()
    description = str(
        item.get("description")
        or item.get("summary")
        or item.get("Summary")
        or item.get("location")
        or item.get("LocationDescriptor")
        or item.get("Area")
        or item.get("area")
        or ""
    ).strip()
    location = str(item.get("location") or item.get("Area") or item.get("area") or "").strip()
    timestamp = str(item.get("timestamp") or item.get("published") or item.get("Published") or item.get("updated") or item.get("Updated") or "").strip()
    url = str(item.get("url") or item.get("Link") or item.get("link") or "").strip()
    try:
        priority_rank = int(item.get("priority_rank") or 0)
    except (TypeError, ValueError):
        priority_rank = 0
    priority_label = str(item.get("priority_label") or item.get("priority") or alert_priority(source, title)[1]).strip() or "News"

    normalized = {
        **item,
        "id": build_alert_id(item, region),
        "source": source,
        "title": title,
        "description": description,
        "priority": priority_label,
        "type": source,
        "timestamp": timestamp,
        "region": region,
        "location": location,
        "url": url,
        "published": timestamp,
        "priority_rank": priority_rank,
        "priority_label": priority_label,
    }
    return normalized


def _safe_field(value: object, default: str = "") -> str:
    text = str(value if value is not None else default)
    return re.sub(r"\s+", " ", text).strip()


def fetch_swedish_alerts(limit: int = 12, region: str = "nacka") -> dict:
    selected_region = normalize_alert_region(region)
    try:
        limit_value = max(1, int(limit))
    except (TypeError, ValueError):
        limit_value = 12

    cache_ttl = timedelta(minutes=15)
    baseline_limit = 180 if selected_region == "sweden" else 60
    fetch_limit = max(limit_value, baseline_limit)
    now = datetime.now()

    with _SWEDISH_ALERTS_CACHE_LOCK:
        cached_entry = _SWEDISH_ALERTS_CACHE.get(selected_region)
        if cached_entry:
            cached_at = cached_entry.get("last_fetched")
            cached_result = cached_entry.get("result")
            if isinstance(cached_at, datetime) and isinstance(cached_result, dict):
                if now - cached_at < cache_ttl:
                    cached_items = list(cached_result.get("items") or [])[:limit_value]
                    return {**cached_result, "items": cached_items, "count": len(cached_items)}

    items: list[dict] = []
    source_errors: list[str] = []
    area_statistics: dict[str, str] = {}
    polisen_data_cache: list[dict] = []
    days_back = 30
    active_sources: list[str] = []

    def _as_items(payload: object, keys: list[str]) -> list[dict]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
        return []

    # ------------------------------------------------------------------ Polisen
    polisen_data = _fetch_json_safely("Polisen", "https://polisen.se/api/events", timeout=5.0)
    if isinstance(polisen_data, list):
        active_sources.append("Polisen")
        polisen_data_cache = [entry for entry in polisen_data if isinstance(entry, dict)]
        for entry in polisen_data_cache:
            title = _safe_field(entry.get("name"), "Polisen event")
            summary = _safe_field(entry.get("summary"))
            location = polisen_location_name(entry)
            published = _safe_field(entry.get("datetime"))
            if not match_region_text(selected_region, title, location, summary):
                continue
            if not is_within_last_days(published, days=days_back):
                continue

            priority_rank, priority_label = alert_priority("Polisen", title)
            items.append(
                {
                    "source": "Polisen",
                    "title": title,
                    "description": summary or location,
                    "url": entry.get("url") or "https://polisen.se/aktuellt/",
                    "published": published,
                    "location": location,
                    "priority_rank": priority_rank,
                    "priority_label": priority_label,
                }
            )
        logger.debug("Polisen: fetched %d items", len(polisen_data_cache))
    elif polisen_data is not None:
        source_errors.append("Polisen feed returned invalid data")

    # --------------------------------------------------------- Krisinformation
    krisis_vmas = _fetch_json_safely("Krisinformation", "https://api.krisinformation.se/v3/vmas?language=sv", timeout=4.0)
    krisis_news = _fetch_json_safely(
        "Krisinformation",
        f"https://api.krisinformation.se/v3/news?language=sv&numberOfNewsArticles={max(fetch_limit, 10)}",
        timeout=4.0,
    )

    if krisis_vmas is not None and krisis_news is not None:
        active_sources.append("Krisinformation")
        vma_items = _as_items(krisis_vmas, ["vmas", "items", "data"])
        news_items = _as_items(krisis_news, ["news", "items", "data"])
        scan_limit = max(fetch_limit * 20, 200)

        for entry in vma_items[:scan_limit]:
            title = _safe_field(entry.get("Headline") or entry.get("headline") or entry.get("title"), "VMA")[:100]
            location = _safe_field(entry.get("Area") or entry.get("area"))
            published = _safe_field(entry.get("Published") or entry.get("published") or entry.get("Updated"))
            if not match_region_text(selected_region, title, location):
                continue
            if not is_within_last_days(published, days=days_back):
                continue

            priority_rank, priority_label = alert_priority("Krisinformation VMA", title)
            items.append(
                {
                    "source": "Krisinformation VMA",
                    "title": title,
                    "description": location,
                    "url": entry.get("Link") or entry.get("link") or "https://krisinformation.se/",
                    "published": published,
                    "location": location,
                    "priority_rank": priority_rank,
                    "priority_label": priority_label,
                }
            )

        for entry in news_items[:scan_limit]:
            title = _safe_field(entry.get("Headline") or entry.get("headline") or entry.get("Title") or entry.get("title"), "Alert")[:100]
            location = _safe_field(entry.get("Area") or entry.get("area"))
            published = _safe_field(entry.get("Published") or entry.get("published") or entry.get("Updated") or entry.get("updated"))
            if not match_region_text(selected_region, title, location):
                continue
            if not is_within_last_days(published, days=days_back):
                continue

            priority_rank, priority_label = alert_priority("Krisinformation", title)
            items.append(
                {
                    "source": "Krisinformation",
                    "title": title,
                    "description": location,
                    "url": entry.get("Link") or entry.get("link") or "https://krisinformation.se/",
                    "published": published,
                    "location": location,
                    "priority_rank": priority_rank,
                    "priority_label": priority_label,
                }
            )
        logger.debug("Krisinformation: fetched %d VMAs and %d news items", len(vma_items), len(news_items))
    else:
        source_errors.append("Krisinformation feed returned invalid data")

    # ---------------------------------------------------------------- SOS Alarm
    # NOTE: Nacka-endpointen returnerar bara statistik, inga larm-items.
    # Använd http:// — https://www. ger robots-block.
    if selected_region == "nacka":
        sos_url = "http://henrikhjelm.se/api/sos/Nacka_kommun.json"
    else:
        sos_url = "http://henrikhjelm.se/api/sos/"

    sos_data = _fetch_json_safely("SOS Alarm", sos_url, timeout=4.0)

    if selected_region == "nacka" and isinstance(sos_data, dict):
        # Nacka-endpointen är ett statistik-flöde utan larm-items — det är korrekt beteende
        area_statistics = extract_sos_statistics(sos_data)
        active_sources.append("SOS Alarm")
        logger.debug("SOS Alarm (Nacka): statistics fetched, no alert items expected")
    elif selected_region != "nacka":
        if sos_data is not None:
            active_sources.append("SOS Alarm")
            sos_items = _as_items(sos_data, ["items", "data", "results", "alerts", "events"])
            scan_limit = max(fetch_limit * 20, 200)
            for entry in sos_items[:scan_limit]:
                title = _safe_field(entry.get("headline") or entry.get("title"), "SOS Event")[:100]
                location = _safe_field(entry.get("location"))
                published = _safe_field(entry.get("timestamp") or entry.get("updated") or entry.get("published"))
                if not match_region_text(selected_region, title, location):
                    continue
                if not is_within_last_days(published, days=days_back):
                    continue

                priority_rank, priority_label = alert_priority("SOS Alarm", title)
                items.append(
                    {
                        "source": "SOS Alarm",
                        "title": title,
                        "description": location,
                        "url": entry.get("url") or "https://www.sosalarm.se/",
                        "published": published,
                        "location": location,
                        "priority_rank": priority_rank,
                        "priority_label": priority_label,
                    }
                )
            logger.debug("SOS Alarm: fetched %d items", len(sos_items))
        else:
            source_errors.append("SOS Alarm feed returned invalid data")

    # ------------------------------------------------------------ Dedup + sort
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = ((item.get("source") or "").strip(), (item.get("title") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    deduped.sort(
        key=lambda item: (
            -int(item.get("priority_rank") or 0),
            -published_sort_value(item.get("published") or ""),
            (item.get("title") or ""),
        )
    )

    if selected_region == "sweden":
        deduped = balance_items_by_source(deduped)

    # ----------------------------------------- Stockholm broader Polisen fallback
    if not deduped and selected_region == "stockholm" and polisen_data_cache:
        fallback_seen: set[tuple[str, str]] = set()
        for entry in polisen_data_cache[: max(fetch_limit * 10, 120)]:
            title = _safe_field(entry.get("name"), "Polisen event")
            if not title:
                continue
            key = ("Polisen", title.strip())
            if key in fallback_seen:
                continue
            fallback_seen.add(key)
            deduped.append(
                {
                    "source": "Polisen",
                    "title": title,
                    "description": entry.get("summary") or _safe_text(polisen_location_name(entry)),
                    "url": entry.get("url") or "https://polisen.se/aktuellt/",
                    "published": entry.get("datetime") or "",
                    "location": polisen_location_name(entry),
                    "priority_rank": alert_priority("Polisen", title)[0],
                    "priority_label": "Police",
                }
            )
            if len(deduped) >= limit_value:
                break

        if deduped:
            source_errors.append(f"{selected_region}: local filter empty; using broader Polisen fallback")

    deduped = deduped[:fetch_limit]
    normalized_items = [normalize_alert_item(item, region=selected_region) for item in deduped]

    result = {
        "items": normalized_items,
        "count": len(normalized_items),
        "region": selected_region,
        "statistics": area_statistics if selected_region == "nacka" else {},
        "errors": source_errors if source_errors else [],
        "sources": active_sources,
    }

    if not normalized_items:
        logger.warning("news_alerts: Swedish alerts temporarily unavailable.")
    elif source_errors:
        logger.warning("news_alerts: Swedish alerts fetched with partial source availability.")
    else:
        logger.debug("news_alerts: Swedish alerts fetched successfully from %s.", ", ".join(active_sources))

    with _SWEDISH_ALERTS_CACHE_LOCK:
        _SWEDISH_ALERTS_CACHE[selected_region] = {
            "last_fetched": now,
            "result": result,
        }

    visible_items = list(result["items"] or [])[:limit_value]
    return {**result, "items": visible_items, "count": len(visible_items)}


def _safe_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
