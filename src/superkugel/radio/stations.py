"""Kuratierte Radiosender (Live-Streams) und ihre stündliche Erreichbarkeitsprüfung.

Nur offizielle HTTPS-Streams, die der ORF selbst für Webradio-Player veröffentlicht (z. B. oe1.orf.at,
„Ö1 Webradio“). Geprüft am 27.10.2026: alle Adressen liefern über HTTPS direkt ``audio/mpeg`` (192 kbit/s),
ohne Weiterleitung. Ausdrückliche Bedingungen des ORF für die Einbindung in fremde Skills wurden nicht gefunden
→ Nutzung nur privat und nicht-kommerziell; Freigabe durch den Admin (docs/plan-erweiterungen-v1.2.md).
"""

from __future__ import annotations

import concurrent.futures as cf
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from superkugel.config import Settings
from superkugel.language import plain
from superkugel.services import net
from superkugel.services.logs import log, metric
from superkugel.services.storage import Store

TOKEN_PREFIX = "radio-"  # noqa: S105 - kein Passwort, Präfix im AudioPlayer-Token
BASE = "https://orf-live.ors-shoutcast.at/"
PROBE_TIMEOUT_S = 3.0
HEALTH_MAX_AGE_S = 3 * 3600  # ältere Prüfungen zählen nicht (dann einfach abspielen)


@dataclass(frozen=True)
class Station:
    station_id: str
    name: str  # so wird der Sender angesagt
    url: str
    aliases: tuple[str, ...]


NATIONAL = (
    Station("oe1", "Ö1", BASE + "oe1-q2a", ("ö1", "ö eins", "österreich eins", "oe eins", "ö 1", "radio österreich eins")),
    Station("oe3", "Ö3", BASE + "oe3-q2a", ("ö3", "ö drei", "österreich drei", "oe drei", "ö 3", "hitradio ö3")),
    Station("fm4", "FM4", BASE + "fm4-q2a", ("fm4", "fm vier", "ef em vier", "fm 4")),
)

# ORF-Regionalradio des Bundeslandes aus USER_REGION (nur das eigene – kurze, übersichtliche Liste)
REGIONAL = {
    "Kärnten": Station("ktn", "Radio Kärnten", BASE + "ktn-q2a", ("radio kärnten", "kärnten", "orf kärnten",
                                                                  "kärnten heute", "radio kärnten live")),
    "Steiermark": Station("stm", "Radio Steiermark", BASE + "stm-q2a", ("radio steiermark", "steiermark")),
    "Wien": Station("wie", "Radio Wien", BASE + "wie-q2a", ("radio wien", "wien")),
    "Niederösterreich": Station("noe", "Radio Niederösterreich", BASE + "noe-q2a",
                                ("radio niederösterreich", "niederösterreich")),
    "Oberösterreich": Station("ooe", "Radio Oberösterreich", BASE + "ooe-q2a",
                              ("radio oberösterreich", "oberösterreich")),
    "Salzburg": Station("sbg", "Radio Salzburg", BASE + "sbg-q2a", ("radio salzburg", "salzburg")),
    "Tirol": Station("tir", "Radio Tirol", BASE + "tir-q2a", ("radio tirol", "tirol")),
    "Vorarlberg": Station("vbg", "Radio Vorarlberg", BASE + "vbg-q2a", ("radio vorarlberg", "vorarlberg")),
    "Burgenland": Station("bgl", "Radio Burgenland", BASE + "bgl-q2a", ("radio burgenland", "burgenland")),
}

_FILLER = {"radio", "sender", "den", "die", "das", "bitte", "live", "orf", "spiel", "spiele", "mal", "hoeren",
           "programm", "mir", "einschalten", "an", "auf"}


def stations(settings: Settings) -> list[Station]:
    """Regionalsender zuerst (der wichtigste für sie), dann Ö1, Ö3, FM4."""
    regional = REGIONAL.get(settings.user_region)
    return ([regional] if regional else []) + list(NATIONAL)


def _key(text: str) -> str:
    return "".join(w for w in plain(text).split() if w not in _FILLER)


def match(raw: str, settings: Settings) -> Station | None:
    """Sendername aus dem Gesagten („Radio Kärnten“, „Ö eins“, „FM vier“). Nur exakte Treffer – kein Raten."""
    key = _key(raw)
    if not key:
        return None
    for st in stations(settings):
        if key in {_key(a) for a in (st.name, st.station_id, *st.aliases)}:
            return st
    return None


def by_id(station_id: str, settings: Settings) -> Station | None:
    return next((s for s in stations(settings) if s.station_id == station_id), None)


def token_for(station: Station) -> str:
    return TOKEN_PREFIX + station.station_id


def station_from_token(token: str | None, settings: Settings) -> Station | None:
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    return by_id(token[len(TOKEN_PREFIX):], settings)


def prompt_block(settings: Settings) -> str:
    """Senderliste für den Systemprompt (eigene, feste Daten – keine fremden Inhalte)."""
    return "Senderliste (Radio live): " + " | ".join(f"station_id={s.station_id}: {s.name}" for s in stations(settings))


def listing(settings: Settings) -> str:
    names = [s.name for s in stations(settings)]
    return ", ".join(names[:-1]) + " und " + names[-1] if len(names) > 1 else names[0]


# ------------------------------------------------------------------ Erreichbarkeit
Prober = Callable[[str, float], tuple[int, str]]


def _alive(url: str, prober: Prober) -> bool:
    try:
        status, ctype = prober(url, PROBE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        log("radio_probe_failed", error=type(exc).__name__)
        return False
    return 200 <= status < 300 and ctype.lower().startswith(("audio/", "application/ogg"))


def check_health(store: Store, settings: Settings, prober: Prober = net.probe,
                 clock: Callable[[], float] = time.time) -> list[str]:
    """Alle Sender parallel per HEAD prüfen (läuft im stündlichen Abruf); Ergebnis: IDs toter Sender."""
    sts = stations(settings)
    with cf.ThreadPoolExecutor(max_workers=len(sts)) as pool:
        alive = dict(zip([s.station_id for s in sts], pool.map(lambda s: _alive(s.url, prober), sts), strict=True))
    down = [sid for sid, ok in alive.items() if not ok]
    store.put_item("RADIO", "HEALTH", {"down": down, "checked": len(sts), "at": clock()})
    if down:
        metric("RadioStationDown", len(down))
    log("radio_health", checked=len(sts), down=len(down))
    return down


def is_down(store: Store, station: Station, settings: Settings, clock: Callable[[], float] = time.time) -> bool:
    """Nur „tot“, wenn die letzte Prüfung frisch ist und nicht ALLE Sender ausfielen (das deutet auf ein Problem
    der Prüfung selbst hin, z. B. Netz/Sperre in AWS – dann lieber abspielen als fälschlich absagen)."""
    try:
        h: dict[str, Any] | None = store.get_item("RADIO", "HEALTH")
    except Exception as exc:  # noqa: BLE001
        log("radio_health_read_failed", error=type(exc).__name__)
        return False
    if not h or clock() - float(h.get("at", 0)) > HEALTH_MAX_AGE_S:
        return False
    down = list(h.get("down") or [])
    if len(down) >= int(h.get("checked", len(stations(settings))) or 1):
        return False
    return station.station_id in down
