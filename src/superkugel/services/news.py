"""Nachrichten-Vorrat: öffentliche ORF-Meldungen sammeln und passend auswählen – der Code liest sie vor, nicht die KI.

So kommt keine Meldung doppelt, und „was noch?“ braucht kein festes Stichwort: Die KI ruft nur das Werkzeug
``nachrichten`` auf. Die Rangfolge bevorzugt Interessen (privat, ``NEWS_INTERESTS``) und Regionales; Aufregendes bleibt
Beimischung, weil je Ressort höchstens eine Meldung kommt. Ins Log kommen nur Zahlen.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from typing import Any

from superkugel.language import plain
from superkugel.services import net
from superkugel.services.logs import log
from superkugel.services.storage import Store

POOL = ("CONTEXT", "NEWS")
KEEP_S = 36 * 3600
MAX_ITEMS = 70
PER_ANSWER = 3
MAX_REGIONAL = 2
TOLD_TTL_S = 36 * 3600
MAX_TOLD = 150
DESC_MAX = 160
SUBJECT_WEIGHT = {"politik": 2, "inland": 2, "kultur": 2, "wirtschaft": 1, "ausland": 1, "chronik": 1, "lifestyle": 0,
                  "it": 0, "sport": 0}
_GENERAL = frozenset({"neuigkeiten", "nachrichten", "neues", "aktuelles", "aktuell", "heute", "oesterreich", "welt"})


def _child_texts(item: ET.Element) -> dict[str, str]:
    return {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in item}


def _timestamp(fields: dict[str, str]) -> float:
    try:
        if fields.get("date"):
            return dt.datetime.fromisoformat(fields["date"]).timestamp()
        if fields.get("pubDate"):
            return email.utils.parsedate_to_datetime(fields["pubDate"]).timestamp()
    except (TypeError, ValueError):
        pass
    return 0.0


def _first_sentence(text: str) -> str:
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return first if len(first) <= DESC_MAX else ""


def parse_items(data: bytes, regional: bool) -> list[dict[str, Any]]:
    """RSS 2.0 oder RDF → Meldungen. Fremder Text wird wie alle Feed-Inhalte bereinigt."""
    from superkugel.services.current_context import clean_text

    root = ET.fromstring(net.reject_entities(data))  # noqa: S314 - Größe begrenzt, keine Entitäten
    items: list[dict[str, Any]] = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "item":
            continue
        fields = _child_texts(el)
        title = clean_text(fields.get("title", ""))
        if not title:
            continue
        link = fields.get("link") or title
        items.append({"id": hashlib.sha256(link.encode()).hexdigest()[:12], "t": title,
                      "d": _first_sentence(clean_text(fields.get("description", ""), 400)),
                      "s": clean_text(fields.get("subject") or fields.get("category") or "", 40),
                      "r": regional, "at": int(_timestamp(fields))})
    return items


def load_pool(store: Store) -> list[dict[str, Any]]:
    try:
        return list((store.get_item(*POOL) or {}).get("items") or [])
    except Exception as exc:  # noqa: BLE001
        log("news_read_failed", error=type(exc).__name__)
        return []


def store_pool(store: Store, new: Iterable[dict[str, Any]], now: float) -> None:
    """Neue Meldungen ergänzen, alte fallen nach 36 Stunden weg. So reicht der Vorrat auch über ruhige Stunden."""
    merged = {i["id"]: i for i in load_pool(store) if float(i.get("seen", i["at"])) >= now - KEEP_S}
    for item in new:
        merged[item["id"]] = {**item, "seen": int(now)}
    latest = sorted(merged.values(), key=lambda i: float(i["at"]), reverse=True)[:MAX_ITEMS]
    store.put_item(*POOL, {"items": latest, "at": int(now)})


def _subject_key(item: dict[str, Any]) -> str:
    words = plain(str(item.get("s", ""))).split()
    return words[0] if words else ""


def _text_of(item: dict[str, Any]) -> str:
    return plain(f"{item.get('t', '')} {item.get('d', '')} {item.get('s', '')}")


def _score(item: dict[str, Any], interests: tuple[str, ...], now: float) -> float:
    text = _text_of(item)
    score = 3.0 if item.get("r") else 0.0
    score += SUBJECT_WEIGHT.get(_subject_key(item), 1)
    score += 4.0 if any(plain(w) in text for w in interests if w.strip()) else 0.0
    return score - max(0.0, now - float(item.get("at", 0))) / (12 * 3600)


def _wished(wish: str, region: str) -> tuple[list[str], bool]:
    """Suchwörter aus Ort und Thema; ``True``, wenn das eigene Bundesland gemeint ist."""
    words = [w for w in plain(wish).split() if len(w) >= 4 and w not in _GENERAL]
    home = plain(region)
    return [w for w in words if w != home], bool(home and home in words)


def select(items: list[dict[str, Any]], told: set[str], wish: str, interests: tuple[str, ...], now: float,
           region: str = "") -> list[dict[str, Any]]:
    """Bis zu drei noch nicht erzählte Meldungen. Mit Wunsch nur Passendes, sonst eine gemischte Auswahl."""
    fresh = sorted((i for i in items if i["id"] not in told), key=lambda i: _score(i, interests, now), reverse=True)
    words, home = _wished(wish, region)
    if words:
        return [i for i in fresh if any(w in _text_of(i) for w in words)][:PER_ANSWER]
    if home:
        return [i for i in fresh if i.get("r")][:PER_ANSWER]
    picked: list[dict[str, Any]] = []
    subjects: set[str] = set()
    regional = 0
    for item in fresh:
        key = _subject_key(item)
        if item.get("r"):
            if regional >= MAX_REGIONAL:
                continue
            regional += 1
        elif key in subjects:
            continue
        else:
            subjects.add(key)
        picked.append(item)
        if len(picked) == PER_ANSWER:
            return picked
    rest = [i for i in fresh if i not in picked and _subject_key(i) != "chronik"]
    return picked + rest[:PER_ANSWER - len(picked)]


def spoken(items: list[dict[str, Any]]) -> str:
    parts = []
    for item in items:
        parts.append(str(item["t"]).rstrip(".!? ") + ".")
        if item.get("d"):
            parts.append(str(item["d"]))
    return " ".join(parts)


def told_ids(store: Store, user: str) -> set[str]:
    try:
        return set((store.get_item(f"USER#{user}", "NEWS_TOLD") or {}).get("ids") or [])
    except Exception as exc:  # noqa: BLE001 - ohne Merkliste kann sich höchstens etwas wiederholen
        log("news_told_read_failed", error=type(exc).__name__)
        return set()


def remember_told(store: Store, user: str, known: set[str], items: list[dict[str, Any]]) -> None:
    ids = [*sorted(known), *(i["id"] for i in items)][-MAX_TOLD:]
    try:
        store.put_item(f"USER#{user}", "NEWS_TOLD", {"ids": ids}, ttl_s=TOLD_TTL_S)
    except Exception as exc:  # noqa: BLE001
        log("news_told_save_failed", error=type(exc).__name__)
