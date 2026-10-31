"""Fahrplanfrage aus einem gesprochenen Satz lesen – ohne KI.

„wann fährt der nächste Zug nach Klagenfurt“, „wie komm ich morgen um halb neun nach Bergdorf“,
„wann geht der letzte Bus von Klagenfurt heim“, „nächster Bus“.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from superkugel.language import fold, word_to_int

_TRAIN = re.compile(r"\b(zug|züge|zuges|bahn|s-bahn|sbahn|railjet|eisenbahn|schnellzug|regionalzug)\b")
_BUS = re.compile(r"\b(bus|busse|busses|postbus|rufbus|autobus|stadtbus)\b")
_TRANSIT = re.compile(r"\b(zug|züge|bahn|s-bahn|railjet|bus|busse|postbus|rufbus|autobus|verbindung|verbindungen|"
                      r"fahrplan|busfahrplan|zugfahrplan|abfahrt|abfahrten|umsteigen|öffis?)\b")
_TRAVEL = re.compile(r"\b(komm|komme|kommt|fahr|fahre|fährt|fahren|reisen?)\b.*\b(nach|zum|zur|heim|nach hause)\b")
_LAST = re.compile(r"\b(letzte|letzter|letzten|zuletzt)\b")
_HOME = re.compile(r"\b(heim|nach hause|nachhause|zu hause|zuhause|daheim)\b")
_WEEKDAYS = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag")
_PART = {"früh": "am", "in der früh": "am", "morgens": "am", "vormittag": "am", "vormittags": "am",
         "mittag": "noon", "mittags": "noon", "nachmittag": "pm", "nachmittags": "pm", "abend": "pm",
         "abends": "pm", "nacht": "pm", "nachts": "pm"}
# Wörter, an denen ein Ortsname sicher zu Ende ist
_PLACE_END = re.compile(r"\s+\b(heute|morgen|übermorgen|um|gegen|ab|am|nach|von|vom|mit|noch|bitte|fährt|fahren|"
                        r"geht|kommt|komm|komme|und|oder|in der|abends?|früh|vormittags?|nachmittags?|mittags?|"
                        r"zurück|jetzt|gleich|wann|wie|der|die|das|den|dem|ein|einen|eine|heim|nach hause|zu hause|daheim|"
                        r"zum|zur|bis|richtung|"
                        + "|".join(_WEEKDAYS) + r")\b.*$")


@dataclass
class TransitQuery:
    mode: str = "any"  # any | bus | train
    last: bool = False
    origin: str = ""  # gesprochener Name, "" = zu Hause
    dest: str = ""  # gesprochener Name, "" = keine (→ Abfahrten)
    dest_home: bool = False
    origin_home: bool = False
    day: dt.date | None = None
    time_s: int | None = None  # Sekunden ab Mitternacht; None = jetzt
    day_said: bool = False


def looks_like_transit(text: str) -> bool:
    t = fold(text)
    return bool(_TRANSIT.search(t)) or bool(_TRAVEL.search(t) and re.search(r"\b(wie|wann)\b", t))


def _place_after(t: str, words: str) -> str:
    m = re.search(rf"\b(?:{words})\s+(.+)$", t)
    if not m:
        return ""
    rest = m.group(1)
    rest = re.sub(r"^(der|die|das|den|dem)\s+", "", rest)
    return _PLACE_END.sub("", " " + rest).strip()


def _parse_time(t: str, now: dt.datetime) -> tuple[dt.date, int | None, bool]:
    day, said = now.date(), False
    if re.search(r"\bübermorgen\b", t):
        day, said = day + dt.timedelta(days=2), True
    elif re.search(r"\bmorgen\b(?!s)", t) and not re.search(r"\bguten morgen\b", t):
        day, said = day + dt.timedelta(days=1), True
    elif re.search(r"\bheute\b", t):
        said = True
    else:
        for i, wd in enumerate(_WEEKDAYS):
            if re.search(rf"\b{wd}s?\b", t):
                day, said = day + dt.timedelta(days=(i - now.weekday()) % 7), True
                break
    part = next((v for k, v in sorted(_PART.items(), key=lambda kv: -len(kv[0])) if re.search(rf"\b{k}\b", t)), "")
    h = m = None
    w = r"(\d{1,2}|[a-zäöüß]+)"
    if mt := re.search(rf"\b(?:um|gegen|ab)\s+(halb|viertel nach|viertel vor|viertel|dreiviertel)\s+{w}\b", t):
        kind, base = mt.group(1), word_to_int(mt.group(2))
        if base is not None:
            h, m = {"halb": (base - 1, 30), "viertel nach": (base, 15), "viertel vor": (base - 1, 45),
                    "viertel": (base - 1, 15), "dreiviertel": (base - 1, 45)}[kind]
    elif mt := re.search(rf"\b(?:um|gegen|ab)\s+{w}(?:\s*uhr)?(?:\s+{w})?\b", t):
        h = word_to_int(mt.group(1))
        m = word_to_int(mt.group(2)) if mt.group(2) else 0
        if m is None:
            m = 0
    elif mt := re.search(r"\b(\d{1,2})[:.](\d{2})\b", t):
        h, m = int(mt.group(1)), int(mt.group(2))
    if h is None or not (0 <= h <= 24) or not (0 <= (m or 0) < 60):
        if part == "am" and said:
            return day, 6 * 3600, said
        if part in ("pm", "noon") and said:
            return day, {"pm": 17, "noon": 12}[part] * 3600, said
        return day, None, said
    h = h % 24
    if part == "pm" and h < 12:
        h += 12
    elif not part and 1 <= h <= 6:
        h += 12  # „um drei“ heißt beim Fahren meist nachmittags
    secs = h * 3600 + (m or 0) * 60
    if not said and secs < now.hour * 3600 + now.minute * 60 - 1800:
        day = day + dt.timedelta(days=1)  # Uhrzeit heute schon vorbei → morgen
    return day, secs, said


def parse(text: str, now: dt.datetime) -> TransitQuery:
    t = fold(text)
    q = TransitQuery()
    if _TRAIN.search(t):
        q.mode = "train"
    elif _BUS.search(t):
        q.mode = "bus"
    q.last = bool(_LAST.search(t))
    q.day, q.time_s, q.day_said = _parse_time(t, now)
    if _HOME.search(t):
        if re.search(r"\b(von|ab)\s+(zu hause|zuhause|daheim)\b", t):
            q.origin_home = True
        else:
            q.dest_home = True
    q.origin = _place_after(t, r"von|vom|ab") if not q.origin_home else ""
    q.dest = "" if q.dest_home else _place_after(t, r"nach|zum|zur|bis|richtung")
    for attr in ("origin", "dest"):  # „ab acht“, „nach halb neun“ sind Zeiten, keine Orte
        val = getattr(q, attr)
        if val and (word_to_int(val.split()[0]) is not None or val.split()[0] in ("halb", "viertel", "dreiviertel")):
            setattr(q, attr, "")
        if val and _HOME.fullmatch(val):
            setattr(q, attr, "")
    return q
