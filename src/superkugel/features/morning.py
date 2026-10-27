"""Morgengruß: Begrüßung, Datum, Wetter, zwei Schlagzeilen – ohne KI und ohne Netzabruf.

Quelle ist nur der stündlich gespeicherte CONTEXT-Eintrag. Veraltete oder fehlende Teile fallen weg.
Belastende Meldungen (Gewalt, Unglücke, Tod) werden über eine einfache Wortliste übersprungen.
Pro Gerät einmal am Tag (Tagesmerker mit TTL, kein Verlauf), nur 5–11 Uhr Wiener Zeit.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from superkugel.config import Settings
from superkugel.language import plain
from superkugel.reminders.parse import MONTH_NAMES, WEEKDAY_NAMES
from superkugel.services.logs import log
from superkugel.services.storage import Store

WINDOW = (5, 11)  # [5:00, 11:00)
FLAG_TTL_S = 2 * 86400
HEADLINE_MAX = 110
RAIN_THRESHOLD = 60  # Prozent → Schirm-Hinweis

# Wortanfänge (nach Umlaut-Auflösung); passt auch auf Wortformen („tödlich“, „Mordprozess“, „Unfalllenker“).
DISTRESSING = (
    "tot", "toet", "tod", "starb", "stirbt", "gestorben", "leiche", "mord", "ermord", "getoetet", "umgebracht",
    "unfall", "unglueck", "verunglueck", "absturz", "abgestuerzt", "crash", "krieg", "angriff", "anschlag",
    "terror", "bombe", "explosion", "schuss", "schuesse", "erschoss", "messer", "erstoch", "gewalt", "vergewalt",
    "missbrauch", "geisel", "entfuehr", "opfer", "verletzt", "schwerverletzt", "katastroph", "erdbeben",
    "hochwasser", "lawine", "brand", "feuer", "suizid", "selbstmord", "amok", "massaker", "folter", "pandemie",
    "mordes", "mordfall", "doppelmord", "raubmord", "verstorb", "toedlich", "ums leben", "bluttat", "femizid",
    "leblos", "vermisst", "sturz",
)
# Kurze Stämme nur am Wortanfang („tot“, nicht „Totale“), längere auch in Zusammensetzungen („Verkehrsunfall“).
_DISTRESS = re.compile(r"\b(" + "|".join(w for w in DISTRESSING if len(w) < 5) + r")|("
                       + "|".join(w for w in DISTRESSING if len(w) >= 5) + r")")


def is_distressing(headline: str) -> bool:
    return bool(_DISTRESS.search(plain(headline)))


def shorten(headline: str, limit: int = HEADLINE_MAX) -> str:
    text = re.sub(r"\s+", " ", headline).strip().rstrip(".!?…")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:–-")


def in_window(local: dt.datetime) -> bool:
    return WINDOW[0] <= local.hour < WINDOW[1]


def _fresh(entry: Any, now: float, max_age_s: float) -> Any:
    if not isinstance(entry, dict) or "at" not in entry:
        return None
    age = now - float(entry["at"])
    return entry.get("value") if -300 <= age <= max_age_s else None


def headlines(context: dict[str, Any], now: float, max_age_s: float, limit: int = 2) -> list[str]:
    """Erst Bundesland, dann Österreich; je eine, Rest auffüllen; belastende überspringen."""
    regional = [h for h in (_fresh(context.get("regional"), now, max_age_s) or []) if not is_distressing(h)]
    national = [h for h in (_fresh(context.get("news"), now, max_age_s) or []) if not is_distressing(h)]
    picked: list[str] = []
    for pool in (regional[:1], national[:1], regional[1:], national[1:]):
        for h in pool:
            if len(picked) < limit and h not in picked:
                picked.append(shorten(h))
    return picked


def weather_today(context: dict[str, Any], now: float, max_age_s: float, today: dt.date) -> dict[str, Any] | None:
    for w in _fresh(context.get("weather"), now, max_age_s) or []:
        if str(w.get("date")) == today.isoformat() and w.get("min") is not None and w.get("max") is not None:
            return w
    return None


def compose(t: Any, settings: Settings, context: dict[str, Any] | None, local: dt.datetime, now: float,
            name: str) -> str:
    """Fertiger Text. ``t`` = Services.t (feste Ansagen aus speech/texts.py)."""
    parts = [t("morning_hello", n=f", {name}" if name else ""),
             t("morning_date", weekday=WEEKDAY_NAMES[local.weekday()], day=local.day,
               month=MONTH_NAMES[local.month - 1])]
    max_age = settings.context_max_age_h * 3600
    ctx = context or {}
    w = weather_today(ctx, now, max_age, local.date())
    if w:
        parts.append(t("morning_weather", desc=w.get("desc") or "wechselhaft", low=round(w["min"]), high=round(w["max"])))
        if (w.get("rain") or 0) >= RAIN_THRESHOLD:
            parts.append(t("morning_rain"))
    news = headlines(ctx, now, max_age)
    if len(news) == 2:
        parts.append(t("morning_news_two", first=news[0], second=news[1]))
    elif news:
        parts.append(t("morning_news_one", first=news[0]))
    return " ".join(parts)


def should_greet(store: Store, settings: Settings, uid: str, local: dt.datetime) -> bool:
    """Zeitfenster, Schalter (Parameter + pro Gerät) und „heute schon begrüßt“ prüfen – und Merker setzen."""
    if not settings.morning_briefing or not in_window(local):
        return False
    today = local.date().isoformat()
    try:
        if (store.get_item(f"USER#{uid}", "PREFS") or {}).get("morning_off"):
            return False
        flags = store.get_item(f"USER#{uid}", "DAYFLAGS") or {}
        if flags.get("date") == today and flags.get("morning"):
            return False
        keep = flags if flags.get("date") == today else {}
        store.put_item(f"USER#{uid}", "DAYFLAGS", {**keep, "date": today, "morning": True}, ttl_s=FLAG_TTL_S)
    except Exception as exc:  # noqa: BLE001 - lieber normale Begrüßung als gar keine
        log("morning_flag_failed", error=type(exc).__name__)
        return False
    return True


def set_enabled(store: Store, uid: str, enabled: bool) -> None:
    prefs = store.get_item(f"USER#{uid}", "PREFS") or {}
    prefs["morning_off"] = not enabled
    store.put_item(f"USER#{uid}", "PREFS", prefs)
