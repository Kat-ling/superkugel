"""Tagesaktuelles Hintergrundwissen (A): ORF-Schlagzeilen und Wetter, stündlich im Hintergrund abgerufen.

Läuft vollständig in AWS (EventBridge-Zeitplan → Lambda), unabhängig vom Admin-PC. Der Skill liest beim
Gespräch nur den gespeicherten Eintrag (ein GetItem) – keine Wartezeit für die Nutzerin.

Datenschutz: Abgerufen werden nur öffentliche Feeds; an Open-Meteo gehen ausschließlich die Koordinaten
des Wohnorts (2 Nachkommastellen ≈ 1 km). Der Ortsname wird nicht an die KI weitergegeben.
Quellen: ORF-RSS („für nicht-kommerzielle Zwecke kostenlos“), Open-Meteo (CC BY 4.0, nicht-kommerziell).
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import html
import json
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo

from superkugel.config import Settings
from superkugel.services import net
from superkugel.services.logs import log, metric
from superkugel.services.storage import Store

MAX_BYTES = 256 * 1024
TIMEOUT_S = 3.0
SOURCES = ("news", "regional", "weather")

ORF_NEWS = "https://rss.orf.at/news.xml"
ORF_REGIONS = {
    "kärnten": "kaernten", "kaernten": "kaernten", "steiermark": "steiermark", "tirol": "tirol",
    "salzburg": "salzburg", "wien": "wien", "niederösterreich": "noe", "noe": "noe",
    "oberösterreich": "ooe", "ooe": "ooe", "burgenland": "burgenland", "vorarlberg": "vorarlberg",
    "niederoesterreich": "noe", "oberoesterreich": "ooe",
}

# WMO-Wettercodes (Open-Meteo) → kurze deutsche Beschreibung
WMO = {0: "sonnig", 1: "überwiegend sonnig", 2: "teils bewölkt", 3: "bedeckt", 45: "Nebel", 48: "Reifnebel",
       51: "leichter Nieselregen", 53: "Nieselregen", 55: "starker Nieselregen", 56: "gefrierender Niesel",
       57: "gefrierender Niesel", 61: "leichter Regen", 63: "Regen", 65: "starker Regen", 66: "gefrierender Regen",
       67: "gefrierender Regen", 71: "leichter Schneefall", 73: "Schneefall", 75: "starker Schneefall",
       77: "Schneegriesel", 80: "Regenschauer", 81: "Regenschauer", 82: "heftige Regenschauer",
       85: "Schneeschauer", 86: "starke Schneeschauer", 95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Gewitter mit Hagel"}

Fetcher = Callable[[str], bytes]


def http_get(url: str) -> bytes:
    return net.reject_entities(net.get_bytes(url, TIMEOUT_S, MAX_BYTES))


_CTRL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")
_QUOTES = re.compile(r"[\"'„“”‚‘’«»‹›`]")


def clean_text(raw: str, max_len: int = 160) -> str:
    """Fremden Text entschärfen: HTML/Entities/Steuer- und Richtungszeichen und Anführungszeichen entfernen,
    Länge begrenzen (Schutz davor, dass Titel im Prompt wie Anweisungen wirken)."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))
    text = unicodedata.normalize("NFKC", _CTRL.sub(" ", text))
    text = _QUOTES.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= max_len else text[: max_len - 1].rsplit(" ", 1)[0] + "…"


def parse_rss_titles(data: bytes, limit: int) -> list[str]:
    """RSS 2.0 oder RSS 1.0/RDF: Titel der Einträge (ohne Namensraum-Abhängigkeit)."""
    root = ET.fromstring(net.reject_entities(data))  # noqa: S314 - Größe begrenzt, keine Entitäten
    titles: list[str] = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "item":
            continue
        for child in el:
            if child.tag.rsplit("}", 1)[-1] == "title" and child.text:
                t = clean_text(child.text)
                if t and t not in titles:
                    titles.append(t)
                break
        if len(titles) >= limit:
            break
    return titles


def parse_weather(data: bytes) -> list[dict[str, Any]]:
    d = json.loads(data)
    daily = d.get("daily") or {}
    days = []
    for i, day in enumerate((daily.get("time") or [])[:2]):
        def val(key: str, i: int = i) -> Any:
            arr = daily.get(key) or []
            return arr[i] if i < len(arr) else None

        code = val("weather_code")
        days.append({"date": str(day), "min": val("temperature_2m_min"), "max": val("temperature_2m_max"),
                     "rain": val("precipitation_probability_max"), "desc": WMO.get(int(code), "") if code is not None else ""})
    return days


def weather_url(lat: float, lon: float, tz: str) -> str:
    return ("https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat:.2f}&longitude={lon:.2f}"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
            f"&timezone={tz.replace('/', '%2F')}&forecast_days=2")


def refresh(store: Store, settings: Settings, fetch: Fetcher = http_get,
            clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """Alle Quellen parallel abrufen; jede Quelle mit eigenem Zeitstempel speichern; Teil-Ausfälle tolerieren."""
    jobs: dict[str, tuple[str, Callable[[bytes], Any]]] = {"news": (ORF_NEWS, lambda b: parse_rss_titles(b, 8))}
    region = ORF_REGIONS.get(settings.user_region.strip().lower())
    if region:
        jobs["regional"] = (f"https://rss.orf.at/{region}.xml", lambda b: parse_rss_titles(b, 5))
    if settings.user_lat is not None and settings.user_lon is not None:
        jobs["weather"] = (weather_url(settings.user_lat, settings.user_lon, settings.timezone), parse_weather)

    old = _safe_get(store) or {}
    now = clock()
    # Bisherige Quellen übernehmen (mit ihrem *eigenen* Zeitstempel) – veraltete fallen später im Prompt weg.
    result: dict[str, Any] = {"region": settings.user_region,
                              **{k: old[k] for k in SOURCES if isinstance(old.get(k), dict) and k in jobs}}
    errors = 0
    with cf.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(fetch, url) for name, (url, _) in jobs.items()}
        for name, fut in futures.items():
            try:
                result[name] = {"value": jobs[name][1](fut.result(timeout=TIMEOUT_S + 1)), "at": now}
            except Exception as exc:  # noqa: BLE001 - eine Quelle darf die anderen nicht verhindern
                errors += 1
                log("context_source_failed", source=name, error=type(exc).__name__)
    store.put_item("CONTEXT", "CURRENT", result)
    if errors:
        metric("ContextRefreshErrors", errors)
    log("context_refreshed", sources=len(jobs), errors=errors)
    return result


def _safe_get(store: Store) -> dict[str, Any] | None:
    try:
        return store.get_item("CONTEXT", "CURRENT")
    except Exception as exc:  # noqa: BLE001
        log("context_read_failed", error=type(exc).__name__)
        return None


def _fresh(entry: Any, now: float, max_age_s: float) -> Any:
    if not isinstance(entry, dict) or "at" not in entry:
        return None
    age = now - float(entry["at"])
    return entry.get("value") if -300 <= age <= max_age_s else None


def prompt_block(store: Store, settings: Settings, clock: Callable[[], float] = time.time) -> str:
    """Text für den Datenteil des Prompts; nur frische Quellen; Heute/Morgen nach Datum."""
    data = _safe_get(store)
    if not data:
        return ""
    now = clock()
    max_age = settings.context_max_age_h * 3600
    tz = ZoneInfo(settings.timezone)
    today = dt.datetime.fromtimestamp(now, tz).date()
    lines: list[str] = []
    stamps: list[float] = []
    news = _fresh(data.get("news"), now, max_age)
    if news:
        lines.append("Schlagzeilen Österreich (ORF): " + " | ".join(news))
        stamps.append(float(data["news"]["at"]))
    regional = _fresh(data.get("regional"), now, max_age)
    if regional:
        lines.append(f"Schlagzeilen {data.get('region') or 'Bundesland'} (ORF): " + " | ".join(regional))
        stamps.append(float(data["regional"]["at"]))
    weather = _fresh(data.get("weather"), now, max_age)
    for w in weather or []:
        try:
            day = dt.date.fromisoformat(str(w.get("date")))
        except ValueError:
            continue
        label = {0: "Heute", 1: "Morgen"}.get((day - today).days)
        if not label:
            continue  # Vorhersage für einen vergangenen Tag nie als aktuell ausgeben
        parts = [w.get("desc") or ""]
        if w.get("min") is not None and w.get("max") is not None:
            parts.append(f"{round(w['min'])} bis {round(w['max'])} Grad")
        if w.get("rain") is not None:
            parts.append(f"Regenwahrscheinlichkeit {round(w['rain'])} Prozent")
        lines.append(f"Wetter {label} an ihrem Wohnort: " + ", ".join(p for p in parts if p))
        stamps.append(float(data["weather"]["at"]))
    if not lines:
        return ""
    stamp = dt.datetime.fromtimestamp(min(stamps), tz).strftime("%H:%M")
    return f"Aktuelles (Stand {stamp} Uhr):\n" + "\n".join(lines)
