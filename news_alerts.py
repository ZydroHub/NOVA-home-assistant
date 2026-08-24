"""Shared Swedish alert fetcher and normalizer for the backend and Telegram bot."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Callable

logger = logging.getLogger(__name__)

_SWEDISH_ALERTS_CACHE_LOCK = threading.Lock()
_SWEDISH_ALERTS_CACHE: dict[str, dict[str, object]] = {}
_ALERT_SEVERITY_CACHE_LOCK = threading.Lock()
_ALERT_SEVERITY_CACHE: dict[str, tuple[int, str]] = {}
_ALERT_SEVERITY_PENDING: set[str] = set()
_ALERT_SEVERITY_LLM_LOCK = threading.Lock()
_ALERT_SEVERITY_LLM = None
AlertSeverityClassifier = Callable[[str, str, str, str, str], str]
PolisenSeverityClassifier = Callable[[str, str, str, str], str]
_ALERT_SEVERITY_CLASSIFIER: AlertSeverityClassifier | None = None
_ALERT_SEVERITY_CLASSIFIER_LOCK = threading.Lock()
ALERT_SEVERITY_RANKS = {
    "LOW": 25,
    "MEDIUM": 50,
    "HIGH": 75,
    "EXTREME": 100,
}
ALERT_SEVERITY_FALLBACK = "MEDIUM"

# Backwards-compatible aliases for existing tests and any internal imports.
_POLISEN_SEVERITY_CACHE_LOCK = _ALERT_SEVERITY_CACHE_LOCK
_POLISEN_SEVERITY_CACHE = _ALERT_SEVERITY_CACHE
POLISEN_SEVERITY_RANKS = ALERT_SEVERITY_RANKS
POLISEN_SEVERITY_FALLBACK = ALERT_SEVERITY_FALLBACK


def register_alert_severity_classifier(classifier: AlertSeverityClassifier | None) -> None:
    """Register a runtime classifier, usually backed by the already loaded chat model."""
    global _ALERT_SEVERITY_CLASSIFIER
    with _ALERT_SEVERITY_CLASSIFIER_LOCK:
        _ALERT_SEVERITY_CLASSIFIER = classifier


def register_polisen_severity_classifier(classifier: PolisenSeverityClassifier | None) -> None:
    if classifier is None:
        register_alert_severity_classifier(None)
        return

    def wrapped(source: str, title: str, summary: str, location: str, published: str) -> str:
        return classifier(title, summary, location, published)

    register_alert_severity_classifier(wrapped)


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


def _severity_match_text(*parts: str) -> str:
    text = " ".join(_safe_text(part) for part in parts).lower()
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", errors="ignore").decode("ascii")
    return f"{text} {ascii_text}"


def _alert_severity_cache_key(
    *,
    source: str,
    title: str,
    summary: str = "",
    location: str = "",
    published: str = "",
    url: str = "",
) -> str:
    seed = "|".join(
        [
            _safe_text(source).lower(),
            _safe_text(title).lower(),
            _safe_text(summary).lower(),
            _safe_text(location).lower(),
            _safe_text(published).lower(),
            _safe_text(url).lower(),
        ]
    )
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()


def _polisen_severity_cache_key(**kwargs) -> str:
    return _alert_severity_cache_key(source="Polisen", **kwargs)


def _normalize_alert_severity(value: object) -> str:
    label = str(value or "").strip().upper()
    return label if label in ALERT_SEVERITY_RANKS else ALERT_SEVERITY_FALLBACK


def _normalize_polisen_severity(value: object) -> str:
    return _normalize_alert_severity(value)


def _alert_severity_result(label: object) -> tuple[int, str]:
    normalized = _normalize_alert_severity(label)
    return ALERT_SEVERITY_RANKS[normalized], normalized


def _polisen_severity_result(label: object) -> tuple[int, str]:
    return _alert_severity_result(label)


def _alert_source_floor_label(source: str) -> str | None:
    source_l = _severity_match_text(source)
    if "krisinformation" in source_l and "vma" in source_l:
        return "EXTREME"
    if "krisinformation" in source_l:
        return "HIGH"
    return None


def _allow_extreme_alert_severity(source: str, title: str, summary: str = "") -> bool:
    source_l = _severity_match_text(source)
    text = _severity_match_text(title, summary)
    if "krisinformation" in source_l and "vma" in source_l:
        return True
    extreme_keywords = (
        "terror",
        "terrorism",
        "masskjut",
        "mass shooting",
        "manga doda",
        "flera doda",
        "manga skadade",
        "katastrof",
        "explosion",
        "bomb",
        "sprangning",
        "skoldad",
        "skolattack",
        "skolskjut",
        "school attack",
        "school shooting",
        "gisslan",
        "pagaende dodligt vald",
        "vma",
        "viktigt meddelande",
    )
    return any(keyword in text for keyword in extreme_keywords)


def _alert_severity_guard_label(source: str, title: str, summary: str = "") -> str | None:
    source_l = _severity_match_text(source)
    text = _severity_match_text(title, summary)
    if "krisinformation" in source_l and "vma" in source_l:
        return "EXTREME"
    if _allow_extreme_alert_severity(source, title, summary):
        return "EXTREME"
    if "polisen" not in source_l:
        return None

    low_keywords = (
        "trafikkontroll",
        "kontroll person",
        "kontroll fordon",
        "nykterhetskontroll",
        "hastighetskontroll",
        "sammanfattning",
        "ovrigt",
        "rattfylleri",
        "stold",
        "bedrageri",
        "olovligt",
        "snatteri",
        "skadegorelse",
        "fimp",
        "balkonglada",
        "inbrott",
    )
    if any(keyword in text for keyword in low_keywords):
        return "LOW"
    return None


def _alert_should_bypass_region(source: str, title: str, summary: str = "") -> bool:
    return _alert_severity_guard_label(source, title, summary) == "EXTREME"


def _include_alert_for_region(
    selected_region: str,
    priority_label: str,
    *region_parts: str,
    global_extreme_alerts: bool = True,
) -> bool:
    if global_extreme_alerts and _normalize_alert_severity(priority_label) == "EXTREME":
        return True
    return match_region_text(selected_region, *region_parts)


def _polisen_severity_guard_label(title: str, summary: str = "") -> str | None:
    return _alert_severity_guard_label("Polisen", title, summary)


def _allow_extreme_polisen_severity(title: str, summary: str = "") -> bool:
    return _allow_extreme_alert_severity("Polisen", title, summary)


def _get_alert_severity_llm():
    global _ALERT_SEVERITY_LLM
    if _ALERT_SEVERITY_LLM is not None:
        return _ALERT_SEVERITY_LLM

    with _ALERT_SEVERITY_LLM_LOCK:
        if _ALERT_SEVERITY_LLM is not None:
            return _ALERT_SEVERITY_LLM

        from huggingface_hub import hf_hub_download
        from llama_cpp import Llama
        from model_settings import get_chat_model_settings_store, get_chat_model_spec

        selected_model = get_chat_model_settings_store().get_selected_model()
        model = get_chat_model_spec(selected_model)
        if not model.path.exists():
            logger.info("Downloading alert severity model %s...", model.label)
            model.path.parent.mkdir(parents=True, exist_ok=True)
            hf_hub_download(repo_id=model.repo_id, filename=model.filename, local_dir=str(model.path.parent))

        try:
            threads = max(1, int(os.getenv("NOVA_LLM_THREADS", str(min(4, os.cpu_count() or 4)))))
        except (TypeError, ValueError):
            threads = min(4, os.cpu_count() or 4)
        _ALERT_SEVERITY_LLM = Llama(
            model_path=str(model.path),
            n_ctx=2048,
            n_threads=threads,
            verbose=False,
        )
        return _ALERT_SEVERITY_LLM


def _get_polisen_severity_llm():
    return _get_alert_severity_llm()


def _classify_alert_severity_with_ai(
    *,
    source: str,
    title: str,
    summary: str = "",
    location: str = "",
    published: str = "",
) -> str:
    with _ALERT_SEVERITY_CLASSIFIER_LOCK:
        classifier = _ALERT_SEVERITY_CLASSIFIER
    if classifier is not None:
        try:
            return str(classifier(source, title, summary, location, published)).strip().upper()
        except Exception as exc:
            logger.debug("Registered alert severity classifier failed; falling back to local loader: %s", exc)

    prompt = (
        "Rank the severity of this Swedish alert for a home alert dashboard.\n"
        "Answer exactly one word: LOW, MEDIUM, HIGH, or EXTREME.\n\n"
        "Rubric:\n"
        "LOW: minor incidents, checks, theft, traffic stops, routine matters.\n"
        "MEDIUM: clear risk or serious local event, fire, accident, ongoing crime without broad public danger.\n"
        "HIGH: serious violent event, major crime, larger accident, active danger to multiple people, large police operation.\n"
        "EXTREME: use only for the worst cases: VMA/important public warning, terrorism, school attack, mass shooting, many dead/injured, disaster, major explosion, or ongoing extreme public danger.\n"
        "A school attack is EXTREME. A VMA from Krisinformation is EXTREME.\n"
        "A single shooting, assault, robbery, or one person badly injured is usually HIGH, not EXTREME.\n\n"
        f"Source: {source}\n"
        f"Title: {title}\n"
        f"Summary: {summary}\n"
        f"Location: {location}\n"
        f"Published: {published}\n"
    )
    llm = _get_alert_severity_llm()
    result = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": "You are a strict alert severity classifier. Output one label only."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=4,
        temperature=0.0,
        stop=["\n", ".", ","],
    )
    try:
        return str(result["choices"][0]["message"]["content"]).strip().upper()
    except (KeyError, IndexError, TypeError):
        return ALERT_SEVERITY_FALLBACK


def _classify_polisen_severity_with_ai(*, title: str, summary: str = "", location: str = "", published: str = "") -> str:
    return _classify_alert_severity_with_ai(
        source="Polisen",
        title=title,
        summary=summary,
        location=location,
        published=published,
    )


def _max_alert_severity_label(first: str, second: str) -> str:
    first_label = _normalize_alert_severity(first)
    second_label = _normalize_alert_severity(second)
    return first_label if ALERT_SEVERITY_RANKS[first_label] >= ALERT_SEVERITY_RANKS[second_label] else second_label


def _finalize_alert_severity_label(source: str, title: str, summary: str, label: object, floor_label: str | None) -> str:
    normalized = _normalize_alert_severity(label)
    if floor_label:
        normalized = _max_alert_severity_label(normalized, floor_label)
    if normalized == "EXTREME" and not _allow_extreme_alert_severity(source, title, summary):
        normalized = "HIGH"
    if floor_label:
        normalized = _max_alert_severity_label(normalized, floor_label)
    return normalized


def _fallback_alert_severity_label(source: str) -> str:
    return _alert_source_floor_label(source) or ALERT_SEVERITY_FALLBACK


def _clear_swedish_alerts_cache() -> None:
    with _SWEDISH_ALERTS_CACHE_LOCK:
        _SWEDISH_ALERTS_CACHE.clear()


def _classify_alert_severity_background(
    *,
    key: str,
    source: str,
    title: str,
    summary: str,
    location: str,
    published: str,
    floor_label: str | None,
) -> None:
    try:
        label = _classify_alert_severity_with_ai(
            source=source,
            title=title,
            summary=summary,
            location=location,
            published=published,
        )
        final_label = _finalize_alert_severity_label(source, title, summary, label, floor_label)
        result = _alert_severity_result(final_label)
        with _ALERT_SEVERITY_CACHE_LOCK:
            _ALERT_SEVERITY_CACHE[key] = result
        _clear_swedish_alerts_cache()
        logger.debug("Alert AI severity updated in background for %s", source or "Alert")
    except Exception as exc:
        logger.debug("%s background AI severity classification failed: %s", source or "Alert", exc)
    finally:
        with _ALERT_SEVERITY_CACHE_LOCK:
            _ALERT_SEVERITY_PENDING.discard(key)


def _schedule_alert_severity_background(
    *,
    key: str,
    source: str,
    title: str,
    summary: str,
    location: str,
    published: str,
    floor_label: str | None,
) -> None:
    with _ALERT_SEVERITY_CACHE_LOCK:
        if key in _ALERT_SEVERITY_PENDING:
            return
        _ALERT_SEVERITY_PENDING.add(key)

    worker = threading.Thread(
        target=_classify_alert_severity_background,
        kwargs={
            "key": key,
            "source": source,
            "title": title,
            "summary": summary,
            "location": location,
            "published": published,
            "floor_label": floor_label,
        },
        name="nova-alert-severity",
        daemon=True,
    )
    worker.start()


def alert_ai_severity(
    *,
    source: str,
    title: str,
    summary: str = "",
    location: str = "",
    published: str = "",
    url: str = "",
    wait_for_ai: bool = True,
) -> tuple[int, str]:
    key = _alert_severity_cache_key(
        source=source,
        title=title,
        summary=summary,
        location=location,
        published=published,
        url=url,
    )
    with _ALERT_SEVERITY_CACHE_LOCK:
        cached = _ALERT_SEVERITY_CACHE.get(key)
        if cached:
            return cached

    guarded_label = _alert_severity_guard_label(source, title, summary)
    if guarded_label:
        result = _alert_severity_result(guarded_label)
        with _ALERT_SEVERITY_CACHE_LOCK:
            _ALERT_SEVERITY_CACHE[key] = result
        return result

    floor_label = _alert_source_floor_label(source)
    if not wait_for_ai:
        fallback_label = _fallback_alert_severity_label(source)
        result = _alert_severity_result(fallback_label)
        with _ALERT_SEVERITY_CACHE_LOCK:
            _ALERT_SEVERITY_CACHE[key] = result
        _schedule_alert_severity_background(
            key=key,
            source=source,
            title=title,
            summary=summary,
            location=location,
            published=published,
            floor_label=floor_label,
        )
        return result

    try:
        label = _classify_alert_severity_with_ai(
            source=source,
            title=title,
            summary=summary,
            location=location,
            published=published,
        )
        result = _alert_severity_result(_finalize_alert_severity_label(source, title, summary, label, floor_label))
    except Exception as exc:
        logger.warning("%s AI severity classification failed; using fallback: %s", source or "Alert", exc)
        result = _alert_severity_result(_fallback_alert_severity_label(source))

    with _ALERT_SEVERITY_CACHE_LOCK:
        _ALERT_SEVERITY_CACHE[key] = result
    return result


def polisen_ai_severity(
    *,
    title: str,
    summary: str = "",
    location: str = "",
    published: str = "",
    url: str = "",
    wait_for_ai: bool = True,
) -> tuple[int, str]:
    return alert_ai_severity(
        source="Polisen",
        title=title,
        summary=summary,
        location=location,
        published=published,
        url=url,
        wait_for_ai=wait_for_ai,
    )


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


def alert_source_sort_rank(source: str) -> int:
    source_l = _severity_match_text(source)
    if "krisinformation" in source_l and "vma" in source_l:
        return 40
    if "krisinformation" in source_l:
        return 30
    if "sos" in source_l:
        return 20
    if "polisen" in source_l:
        return 10
    return 0


def balance_items_by_source(items: list[dict]) -> list[dict]:
    """Interleave sources so one feed does not dominate the Sweden list."""
    if not items:
        return items

    preferred_order = [
        "Krisinformation VMA",
        "Krisinformation",
        "SOS Alarm",
        "Polisen",
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


def fetch_swedish_alerts(limit: int = 12, region: str = "nacka", *, global_extreme_alerts: bool = True) -> dict:
    selected_region = normalize_alert_region(region)
    try:
        limit_value = max(1, int(limit))
    except (TypeError, ValueError):
        limit_value = 12

    cache_ttl = timedelta(minutes=15)
    baseline_limit = 180 if selected_region == "sweden" else max(12, limit_value * 3)
    fetch_limit = max(limit_value, baseline_limit)
    now = datetime.now()
    cache_key = f"{selected_region}:global_extreme={bool(global_extreme_alerts)}"

    with _SWEDISH_ALERTS_CACHE_LOCK:
        cached_entry = _SWEDISH_ALERTS_CACHE.get(cache_key)
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
            if not is_within_last_days(published, days=days_back):
                continue
            region_match = match_region_text(selected_region, title, location, summary)
            if not region_match and (not global_extreme_alerts or not _alert_should_bypass_region("Polisen", title, summary)):
                continue

            url = entry.get("url") or "https://polisen.se/aktuellt/"
            priority_rank, priority_label = polisen_ai_severity(
                title=title,
                summary=summary,
                location=location,
                published=published,
                url=str(url),
                wait_for_ai=False,
            )
            if not _include_alert_for_region(selected_region, priority_label, title, location, summary, global_extreme_alerts=global_extreme_alerts):
                continue
            items.append(
                {
                    "source": "Polisen",
                    "title": title,
                    "description": summary or location,
                    "url": url,
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
            if not is_within_last_days(published, days=days_back):
                continue

            url = entry.get("Link") or entry.get("link") or "https://krisinformation.se/"
            priority_rank, priority_label = alert_ai_severity(
                source="Krisinformation VMA",
                title=title,
                summary=location,
                location=location,
                published=published,
                url=str(url),
                wait_for_ai=False,
            )
            if not _include_alert_for_region(selected_region, priority_label, title, location, global_extreme_alerts=global_extreme_alerts):
                continue
            items.append(
                {
                    "source": "Krisinformation VMA",
                    "title": title,
                    "description": location,
                    "url": url,
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
            if not is_within_last_days(published, days=days_back):
                continue
            region_match = match_region_text(selected_region, title, location)
            if not region_match and (not global_extreme_alerts or not _alert_should_bypass_region("Krisinformation", title, location)):
                continue

            url = entry.get("Link") or entry.get("link") or "https://krisinformation.se/"
            priority_rank, priority_label = alert_ai_severity(
                source="Krisinformation",
                title=title,
                summary=location,
                location=location,
                published=published,
                url=str(url),
                wait_for_ai=False,
            )
            if not _include_alert_for_region(selected_region, priority_label, title, location, global_extreme_alerts=global_extreme_alerts):
                continue
            items.append(
                {
                    "source": "Krisinformation",
                    "title": title,
                    "description": location,
                    "url": url,
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
                if not is_within_last_days(published, days=days_back):
                    continue
                region_match = match_region_text(selected_region, title, location)
                if not region_match and (not global_extreme_alerts or not _alert_should_bypass_region("SOS Alarm", title, location)):
                    continue

                url = entry.get("url") or "https://www.sosalarm.se/"
                priority_rank, priority_label = alert_ai_severity(
                    source="SOS Alarm",
                    title=title,
                    summary=location,
                    location=location,
                    published=published,
                    url=str(url),
                    wait_for_ai=False,
                )
                if not _include_alert_for_region(selected_region, priority_label, title, location, global_extreme_alerts=global_extreme_alerts):
                    continue
                items.append(
                    {
                        "source": "SOS Alarm",
                        "title": title,
                        "description": location,
                        "url": url,
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
            -alert_source_sort_rank(str(item.get("source") or "")),
            -published_sort_value(item.get("published") or ""),
            (item.get("title") or ""),
        )
    )

    if selected_region == "sweden":
        extreme_items = [item for item in deduped if _normalize_alert_severity(item.get("priority_label")) == "EXTREME"]
        remaining_items = [item for item in deduped if _normalize_alert_severity(item.get("priority_label")) != "EXTREME"]
        deduped = extreme_items + balance_items_by_source(remaining_items)

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
            summary = entry.get("summary") or _safe_text(polisen_location_name(entry))
            published = entry.get("datetime") or ""
            location = polisen_location_name(entry)
            url = entry.get("url") or "https://polisen.se/aktuellt/"
            priority_rank, priority_label = polisen_ai_severity(
                title=title,
                summary=str(summary),
                location=location,
                published=str(published),
                url=str(url),
                wait_for_ai=False,
            )
            deduped.append(
                {
                    "source": "Polisen",
                    "title": title,
                    "description": summary,
                    "url": url,
                    "published": published,
                    "location": location,
                    "priority_rank": priority_rank,
                    "priority_label": priority_label,
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
        _SWEDISH_ALERTS_CACHE[cache_key] = {
            "last_fetched": now,
            "result": result,
        }

    visible_items = list(result["items"] or [])[:limit_value]
    return {**result, "items": visible_items, "count": len(visible_items)}


def _safe_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
