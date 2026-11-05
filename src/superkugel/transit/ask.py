"""Fahrplanfrage aus einem gesprochenen Satz lesen – ohne KI.

„wann fährt der nächste Zug nach Klagenfurt“, „wie komm ich morgen um halb neun nach Bergdorf“,
„wann geht der letzte Bus von Klagenfurt heim“, „nächster Bus“, „am 20. November nach Linz“, „in zwei Stunden“.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from superkugel.language import MONTH_NAMES, fold, word_to_int

_TRAIN = re.compile(r"\b(zug|züge|zuges|bahn|s-bahn|sbahn|railjet|eisenbahn|schnellzug|regionalzug)\b")
_BUS = re.compile(r"\b(bus|busse|busses|postbus|rufbus|autobus|stadtbus)\b")
_TRANSIT = re.compile(r"\b(zug|züge|bahn|s-bahn|railjet|bus|busse|postbus|rufbus|autobus|verbindung|verbindungen|"
                      r"fahrplan|busfahrplan|zugfahrplan|abfahrt|abfahrten|umsteigen|öffis?)\b")
_TRAVEL = re.compile(r"\b(komm|komme|kommt|fahr|fahre|fährt|fahren|reisen?)\b.*\b(nach|zum|zur|heim|nach hause)\b")
# „ich möchte morgen nach Bergdorf fahren“, „ich muss zu meiner Schwester nach Bergdorf“: Reiseabsicht ohne „Bus“/„Zug“
_INTENT = re.compile(r"\b(möchte|möcht|möchten|will|wollen|muss|müssen|würde|fahre|fahr|reise|komme|besuche|"
                     r"geh|gehe|hin|komm|kommen|zu (meiner|meinem|meinen|unserer|unserem|unseren))\b")
_INTENT_DEST = re.compile(r"\bnach\s+(?!(?:dem|der|den|des|einem|einer|hause|haus)\b)")
# Zentrum des Heimatorts: „in die Stadt“, „ins Zentrum“ (die Haltestelle sucht der Code aus den Daten)
_TO_CENTER = re.compile(r"\b(in die stadt|ins zentrum|ins stadtzentrum|in die innenstadt|in die city|"
                        r"auf den hauptplatz|zum hauptplatz)\b")
# Kein Reisewunsch der Sprecherin: Verneinung, anderes Verkehrsmittel, Umzug, Vergangenes, Bedingung
_NO_TRIP = re.compile(r"\b(nicht|nie|niemals|kein|keine|keinen|zu fuß|spazieren|laufen|ziehen|umziehen|gezogen|"
                      r"gefahren|gewesen|gestern|vorgestern|früher|damals|wenn|falls|"
                      r"mit dem (auto|rad|fahrrad|taxi)|fliegen|fliege)\b")
# Jemand anderes will reisen: „meine Tochter muss …“, „die wollen …“ (aber: „morgen muss ich …“, „und will …“)
_OTHER_PERSON = re.compile(r"\b(?!ich\b|wir\b|und\b|dann\b|also\b|ja\b|nun\b|aber\b|auch\b|doch\b|bald\b|gern\b|"
                           r"gerne\b|jetzt\b|heute\b|morgen\b|übermorgen\b)[a-zäöüß]+\s+"
                           r"(möchte|möcht|möchten|will|wollen|muss|müssen|würde)\b(?!\s+(ich|wir)\b)")
_LAST = re.compile(r"\b(letzte|letzter|letzten|zuletzt)\b")
_HOME = re.compile(r"\b(heim|nach hause|nachhause|zu hause|zuhause|daheim)\b")
_WEEKDAYS = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag")
_PART = {"früh": "am", "in der früh": "am", "am morgen": "am", "morgens": "am", "vormittag": "am", "vormittags": "am",
         "mittag": "noon", "mittags": "noon", "nachmittag": "after", "nachmittags": "after", "abend": "pm",
         "abends": "pm", "nacht": "pm", "nachts": "pm"}
# Wörter, an denen ein Ortsname sicher zu Ende ist
_PLACE_END = re.compile(r"\s+\b(heute|morgen|übermorgen|um|gegen|ab|am|nach|von|vom|mit|noch|bitte|fährt|fahren|"
                        r"geht|kommt|komm|komme|und|oder|in der|abends?|früh|vormittags?|nachmittags?|mittags?|"
                        r"zurück|jetzt|gleich|wann|wie|der|die|das|den|dem|ein|einen|eine|heim|nach hause|zu hause|daheim|"
                        r"zum|zur|bis|richtung|"
                        + "|".join(_WEEKDAYS) + r")\b.*$")
# Datum: „am 20. November“, „am zwanzigsten Jänner“, „am 20.11.“, „am 20.“
_MONTHS = {**{m.lower(): i for i, m in enumerate(MONTH_NAMES, 1)}, "januar": 1, "jänner": 1, "feber": 2}
_MONTH_WORD = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ORDINALS = {"ersten": 1, "zweiten": 2, "dritten": 3, "vierten": 4, "fünften": 5, "sechsten": 6, "siebten": 7,
             "siebenten": 7, "achten": 8, "neunten": 9, "zehnten": 10, "elften": 11, "zwölften": 12}
_DAY_NO = r"(\d{1,2}\.?|[a-zäöüß]+(?:ten|sten))"
_DATE_MONTH = re.compile(rf"\b(?:am\s+|den\s+|dem\s+)?{_DAY_NO}\s+({_MONTH_WORD})\b")
_DATE_NUM = re.compile(r"\b(?:am|den|dem)\s+(\d{1,2})\.(\d{1,2})\.(?:(\d{2,4})\b)?")
_DATE_DAY = re.compile(rf"\b(?:am|den|dem)\s+{_DAY_NO}(?=\s|$)")
# „in zwei Stunden“, „in einer halben Stunde“, „in drei Tagen“
_RELATIVE = re.compile(r"\bin\s+((?:[a-zäöüß0-9]+\s+){0,2}?)(stunden?|viertelstunde|minuten?|tagen?|wochen?)\b")
_AMOUNT = {"": 1.0, "einer": 1.0, "einem": 1.0, "einen": 1.0, "ein": 1.0, "einer halben": 0.5, "einer viertel": 0.25,
           "einer dreiviertel": 0.75, "dreiviertel": 0.75, "eineinhalb": 1.5, "anderthalb": 1.5, "zweieinhalb": 2.5}
_VAGUE = re.compile(r"\b(nächste woche|nächster woche|übernächste woche|nächstes wochenende|am wochenende|"
                    r"übers wochenende|nächsten monat|nächstes jahr|irgendwann|demnächst|bald einmal|"
                    r"zu weihnachten|zu ostern|zu pfingsten|zu silvester|zu neujahr)\b")
_WHEN_VOCABULARY = """und dann lieber doch eher etwa ungefähr so bitte vielleicht später früher um gegen ab uhr halb
    viertel dreiviertel vor nach heute morgen übermorgen am in der den dem früh abend abends nachmittag nachmittags
    vormittag vormittags mittag mittags nacht nachts nächsten nächster nächste kommenden kommender einer einem einen ein
    halben eineinhalb anderthalb stunde stunden minute minuten viertelstunde tag tagen woche wochen"""
_WHEN_WORDS = frozenset(_WHEN_VOCABULARY.split()) | frozenset(_WEEKDAYS)


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
    vague: bool = False  # „nächste Woche“: Tag unklar → nachfragen statt raten


def looks_like_transit(text: str) -> bool:
    t = fold(text)
    return bool(_TRANSIT.search(t)) or bool(_TRAVEL.search(t) and re.search(r"\b(wie|wann)\b", t))


def only_says_when(text: str) -> bool:
    """Nennt der Satz nur eine Zeit („gegen zehn“, „und am Freitag“)? Dann ändert er nur Zeit oder Tag der Reise."""
    t = fold(text).rstrip(".,? ")
    words = t.replace(",", " ").split()
    if not all(w in _WHEN_WORDS or w.rstrip(".") in _MONTHS or word_to_int(w) is not None or _ordinal(w) is not None
               for w in words):
        return False
    q = parse(text, dt.datetime(2000, 1, 3, 12))
    return q.time_s is not None or q.day_said


def travel_dest(text: str) -> str:
    """Ziel aus einem Reisesatz ohne Verkehrsmittel („ich möchte morgen nach Bergdorf fahren“) – ob es ein Ort ist,
    prüft der Aufrufer (nur bekannte Haltestellen, sonst geht der Satz an die KI)."""
    t = fold(text)
    if not _INTENT.search(t) or _NO_TRIP.search(t) or _OTHER_PERSON.search(t):
        return ""
    dest = _place_after(t, "nach") if _INTENT_DEST.search(t) else ""
    first = dest.split()[0] if dest else ""
    if first and word_to_int(first) is None and first not in ("halb", "viertel", "dreiviertel"):
        return dest
    return "stadtzentrum" if _TO_CENTER.search(t) else ""


def parse_dest(text: str) -> str:
    """Nennt der Satz selbst ein Ziel („… nach Bergdorf“)? Für die Gegenprobe zum KI-Werkzeug."""
    q = parse(text, dt.datetime(2000, 1, 3, 12))
    return q.dest


def _place_after(t: str, words: str) -> str:
    m = re.search(rf"\b(?:{words})\s+(.+)$", t)
    if not m:
        return ""
    rest = m.group(1)
    rest = re.sub(r"^(der|die|das|den|dem)\s+", "", rest)
    return _PLACE_END.sub("", " " + rest).strip()


def _ordinal(word: str) -> int | None:
    """„20.“, „dritten“, „zwanzigsten“, „einundzwanzigsten“ → Tag des Monats."""
    if word.rstrip(".").isdigit():
        return int(word.rstrip("."))
    if word in _ORDINALS:
        return _ORDINALS[word]
    return word_to_int(word[:-4] if word.endswith("sten") else word[:-3])


def _next_date(month: int, number: int, today: dt.date, year: int | None = None) -> dt.date | None:
    """Das nächste Mal, dass dieses Datum kommt; None, wenn es den Tag nicht gibt."""
    for y in ([year] if year else [today.year, today.year + 1]):
        try:
            d = dt.date(y, month, number)
        except ValueError:
            return None
        if year or d >= today:
            return d
    return None


def _parse_date(t: str, today: dt.date) -> tuple[dt.date | None, str]:
    """Datum aus dem Satz und der Rest des Satzes ohne Datum. Ein unmögliches Datum (31. November) → (None, "?")."""
    if m := _DATE_NUM.search(t):
        year = int(m.group(3)) if m.group(3) else None
        year = year + 2000 if year and year < 100 else year
        d = _next_date(int(m.group(2)), int(m.group(1)), today, year) if 1 <= int(m.group(2)) <= 12 else None
        return d, "?" if d is None else t[:m.start()] + t[m.end():]
    if (m := _DATE_MONTH.search(t)) and (number := _ordinal(m.group(1))) is not None:
        d = _next_date(_MONTHS[m.group(2)], number, today)
        return d, "?" if d is None else t[:m.start()] + t[m.end():]
    if (m := _DATE_DAY.search(t)) and (number := _ordinal(m.group(1))) is not None:
        month, year = (today.month, today.year) if number >= today.day else (today.month % 12 + 1, today.year)
        year += 1 if month < today.month else 0
        d = _next_date(month, number, today, year)
        return d, "?" if d is None else t[:m.start()] + t[m.end():]
    return None, t


def _relative(t: str) -> tuple[float, str] | None:
    """„in zwei Stunden“ → (2.0, "stunde"), sonst None."""
    m = _RELATIVE.search(t)
    if not m:
        return None
    said = m.group(1).strip()
    amount = _AMOUNT.get(said)
    if amount is None:
        n = word_to_int(said)
        amount = float(n) if n is not None else None
    if amount is None:
        return None
    unit = m.group(2)
    if unit == "viertelstunde":
        return amount * 15, "minute"
    return amount, next(u for u in ("stunde", "minute", "woche", "tag") if unit.startswith(u))


def _weekday(t: str, today: dt.date) -> dt.date | None:
    """„Dienstag“ = der nächste; „nächsten Dienstag“ nie heute; „nächste Woche Dienstag“ in der Woche darauf."""
    for i, wd in enumerate(_WEEKDAYS):
        if not re.search(rf"\b{wd}s?\b", t):
            continue
        if re.search(r"\bübernächste[nrs]? woche\b", t):
            return today + dt.timedelta(days=14 - today.weekday() + i)
        if re.search(r"\bnächste[nrs]? woche\b", t):
            return today + dt.timedelta(days=7 - today.weekday() + i)
        delta = (i - today.weekday()) % 7
        if delta == 0 and re.search(rf"\b(nächste[nrs]?|kommende[nrs]?)\s+{wd}\b", t):
            delta = 7
        return today + dt.timedelta(days=delta)
    return None


def _strip_when(t: str) -> str:
    """Satz ohne Zeitangaben, die wie Orte aussehen („nach Linz in zwei Stunden“, „nach Linz 20. November“)."""
    if _relative(t):
        t = _RELATIVE.sub("", t, count=1)
    return _parse_date(t, dt.date(2000, 1, 1))[1].replace("?", " ") if t else t


def _parse_time(t: str, now: dt.datetime) -> tuple[dt.date, int | None, bool]:
    today = now.date()
    day, said = today, False
    rel = _relative(t)
    if rel and rel[1] in ("stunde", "minute"):
        target = now + dt.timedelta(hours=rel[0]) if rel[1] == "stunde" else now + dt.timedelta(minutes=rel[0])
        return target.date(), target.hour * 3600 + target.minute * 60, True
    date, t = _parse_date(t, today)
    if rel:
        day, said = today + dt.timedelta(days=int(rel[0]) * (7 if rel[1] == "woche" else 1)), True
    elif date:
        day, said = date, True
    elif re.search(r"\bübermorgen\b", t):
        day, said = day + dt.timedelta(days=2), True
    elif re.search(r"(?<!am )\bmorgen\b(?!s)", t) and not re.search(r"\bguten morgen\b", t):
        day, said = day + dt.timedelta(days=1), True
    elif re.search(r"\bheute\b", t):
        said = True
    elif wd_day := _weekday(t, today):
        day, said = wd_day, True
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
        if not part:  # keine Uhrzeit, keine Tageszeit
            return day, None, said
        h, m = {"am": 6, "noon": 12, "after": 13, "pm": 17}[part], 0  # „am Abend“: ab dann suchen
    h = h % 24
    if part in ("pm", "after") and h < 12:
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
    q.vague = not q.day_said and bool(_VAGUE.search(t) or _parse_date(t, now.date())[1] == "?")
    t = _strip_when(t)
    if _HOME.search(t):
        if re.search(r"\b(von|ab)\s+(zu hause|zuhause|daheim)\b", t):
            q.origin_home = True
        else:
            q.dest_home = True
    q.origin = _place_after(t, r"von|vom|ab") if not q.origin_home else ""
    q.dest = "" if q.dest_home else _place_after(t, r"nach|zum|zur|ins|bis|richtung")
    if not q.dest and not q.dest_home and _TO_CENTER.search(t):
        q.dest = "stadtzentrum"
    for attr in ("origin", "dest"):  # „ab acht“, „nach halb neun“ sind Zeiten, keine Orte
        val = getattr(q, attr)
        first = val.split()[0] if val else ""
        if first and (word_to_int(first) is not None or _ordinal(first) is not None
                      or first in ("halb", "viertel", "dreiviertel")):
            setattr(q, attr, "")
        if val and _HOME.fullmatch(val):
            setattr(q, attr, "")
    return q
