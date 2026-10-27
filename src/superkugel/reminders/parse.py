"""Erinnerungssätze verstehen – deterministisch, ohne KI, immer in Wiener Zeit.

Beispiele: „morgen um zehn an den Arzt“, „in einer Stunde an die Wäsche“, „am Dienstag um halb drei,
dass ich die Oma anrufe“, „übermorgen in der Früh um acht“, „um dreiviertel zehn“ (= 9:45, österreichisch).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from superkugel.language import fold, word_to_int

WEEKDAYS = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag")
WEEKDAY_NAMES = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONTHS = ("jänner", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober",
          "november", "dezember")
MONTH_NAMES = ("Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
               "November", "Dezember")
_MONTH_ALIASES = {"januar": 1, "feber": 2, **{m: i + 1 for i, m in enumerate(MONTHS)}}
_ORDINAL_STEMS = {"ers": 1, "drit": 3, "sieb": 7, "ach": 8}
# Tageszeit → (Art, Standardstunde ohne Uhrzeit). Art: am = vormittags, pm = nachmittags/abends,
# night = „nachts“ (6–11 Uhr → abends, 12 Uhr → Mitternacht, 1–5 Uhr bleibt früh morgens)
_DAYPARTS = {
    "in der früh": ("am", 8), "früh": ("am", 8), "morgens": ("am", 8), "vormittag": ("am", 10),
    "vormittags": ("am", 10), "am vormittag": ("am", 10), "zu mittag": ("am", 12), "mittags": ("am", 12),
    "am nachmittag": ("pm", 15), "nachmittags": ("pm", 15), "nachmittag": ("pm", 15), "am abend": ("pm", 19),
    "abends": ("pm", 19), "abend": ("pm", 19), "in der nacht": ("night", 21), "nachts": ("night", 21),
}
MAX_TEXT = 120
_FILLER = {"bitte", "noch", "mal", "doch", "gell", "eine", "erinnerung", "erinnere", "erinner", "mich", "mir",
           "uns", "stell", "stelle", "mach", "leg", "lege", "an", "ans", "daran", "dran", "dass", "für", "fuer"}


@dataclass
class Draft:
    """Teilweise verstandene Erinnerung (wandert über Sitzungsattribute von Frage zu Frage)."""

    date: str | None = None  # ISO-Datum (Wien)
    time: str | None = None  # "HH:MM" (24 h)
    text: str | None = None
    # None = Uhrzeit mehrdeutig (Heuristiken in ``resolve``); True/False = eindeutig (Tageszeit genannt,
    # 24-h-Angabe oder relative Zeit „in einer Stunde“) → keine Umdeutung
    pm_hint: bool | None = None
    at: str | None = None  # exakter Zeitpunkt (UTC, ISO) bei relativen Zeiten – eindeutig auch in der Umstellungsnacht

    def to_attrs(self) -> dict[str, object]:
        return {"date": self.date, "time": self.time, "text": self.text, "pm_hint": self.pm_hint, "at": self.at}

    @classmethod
    def from_attrs(cls, d: object) -> Draft:
        d = d if isinstance(d, dict) else {}
        return cls(date=d.get("date"), time=d.get("time"), text=d.get("text"), pm_hint=d.get("pm_hint"),
                   at=d.get("at"))

    def merge(self, other: Draft) -> Draft:
        # Eine neue Uhrzeit bringt ihre eigene Eindeutigkeit mit
        pm = other.pm_hint if other.time or other.pm_hint is not None else self.pm_hint
        at = other.at if (other.date or other.time) else self.at
        return Draft(date=other.date or self.date, time=other.time or self.time, text=other.text or self.text,
                     pm_hint=pm, at=at)


def ordinal_to_int(word: str) -> int | None:
    """„dritten“ → 3, „einundzwanzigsten“ → 21, „3.“ → 3."""
    w = word.strip().rstrip(".")
    if w.isdigit():
        return int(w)
    stem = re.sub(r"(sten|stem|ster|ste|ten|tem|ter|te)$", "", w)
    if stem in _ORDINAL_STEMS:
        return _ORDINAL_STEMS[stem]
    if stem.endswith(tuple(f"und{t}" for t in ("zwanzig", "dreißig", "dreissig"))) or stem.endswith(
            ("zwanzig", "dreißig", "dreissig")):
        return word_to_int(stem)
    n = word_to_int(stem)
    return n if n is not None and 1 <= n <= 31 else None


_NUM = r"[a-zäöüß0-9]+"


def _hour(word: str) -> int | None:
    n = word_to_int(word)
    return n if n is not None and 0 <= n <= 24 else None


def _parse_clock(s: str) -> tuple[tuple[int, int] | None, str]:
    """Findet eine Uhrzeit (mit „um“ oder „uhr“). Gibt ((h, m), Rest ohne Uhrzeit) zurück."""
    patterns: list[tuple[str, object]] = [
        (rf"\bum (?:ein )?viertel nach ({_NUM})(?: uhr)?\b", lambda m: (_hour(m[1]), 15)),
        (rf"\bum (?:ein )?viertel vor ({_NUM})(?: uhr)?\b", lambda m: (_dec(_hour(m[1])), 45)),
        (rf"\bum dreiviertel ({_NUM})(?: uhr)?\b", lambda m: (_dec(_hour(m[1])), 45)),
        (rf"\bum viertel ({_NUM})(?: uhr)?\b", lambda m: (_dec(_hour(m[1])), 15)),
        (rf"\bum halb ({_NUM})(?: uhr)?\b", lambda m: (_dec(_hour(m[1])), 30)),
        # „um zehn nach drei“ = 3:10, „um fünf vor acht“ = 7:55
        (rf"\bum ({_NUM}) nach ({_NUM})(?: uhr)?\b", lambda m: (_hour(m[2]), _minute(m[1]))),
        (rf"\bum ({_NUM}) vor ({_NUM})(?: uhr)?\b", lambda m: (_dec(_hour(m[2])), _before(m[1]))),
        (r"\bum (\d{1,2})[:.](\d{2})(?: uhr)?\b", lambda m: (_hour(m[1]), int(m[2]))),
        (rf"\bum ({_NUM}) uhr(?: ({_NUM}))?\b", lambda m: (_hour(m[1]), _minute(m[2]))),
        (rf"\b({_NUM}) uhr(?: ({_NUM}))?\b", lambda m: (_hour(m[1]), _minute(m[2]))),
        (rf"\bum ({_NUM})\b", lambda m: (_hour(m[1]), 0)),
    ]
    for pat, conv in patterns:
        for m in re.finditer(pat, s):  # „um den Arzt … um zehn“: erstes „um“ ist keine Uhrzeit
            h, minute = conv(m)  # type: ignore[operator]
            if h is None or minute is None or not 0 <= minute <= 59:
                continue
            if h in (0, 24) and minute == 0:  # „um 24 Uhr“ / „um null Uhr“ = Mitternacht
                h = 24
            return (h if h == 24 else h % 24, minute), (s[: m.start()] + " " + s[m.end():])
    if re.search(r"\b(um )?mitternacht\b", s):
        return (24, 0), re.sub(r"\b(um )?mitternacht\b", " ", s)
    return None, s


def _dec(h: int | None) -> int | None:
    return None if h is None else (h - 1) % 24


def _before(word: str) -> int | None:
    n = _minute(word)
    return None if not n else 60 - n


def _minute(word: str | None) -> int | None:
    if not word:
        return 0
    n = word_to_int(word)
    return n if n is not None and 0 <= n <= 59 else None


def _parse_relative(s: str) -> tuple[dt.timedelta | int | None, str]:
    """„in einer halben Stunde“ → timedelta; „in zwei Tagen“ / „in einer Woche“ → Anzahl Tage (int; die Uhrzeit
    kommt dann aus dem Rest des Satzes)."""
    m = re.search(rf"\bin (einer |einem |eineinhalb |anderthalb |{_NUM} )?(halben |dreiviertel |viertel)?"
                  r"(stunde|stunden|minute|minuten|viertelstunde|tag|tagen|woche|wochen)\b", s)
    if not m:
        return None, s
    raw = (m[1] or "").strip()
    count: float | None
    if raw in ("", "einer", "einem"):
        count = 1
    elif raw in ("eineinhalb", "anderthalb"):
        count = 1.5
    else:
        count = word_to_int(raw)
    if count is None:
        return None, s
    unit, rest = m[3], s[: m.start()] + " " + s[m.end():]
    if unit.startswith("tag"):
        return int(count), rest
    if unit.startswith("woche"):
        return int(count * 7), rest
    if unit == "viertelstunde":
        minutes = 15 * count
    elif unit.startswith("stunde"):
        frac = {"halben ": 0.5, "dreiviertel ": 0.75, "viertel": 0.25}.get(m[2] or "", 1.0)
        minutes = 60 * count * frac
    else:
        minutes = count
    return dt.timedelta(minutes=round(minutes)), rest


def _parse_date(s: str, today: dt.date) -> tuple[dt.date | None, str]:
    rules: list[tuple[str, object]] = [
        (r"\bübermorgen\b", lambda m: today + dt.timedelta(days=2)),
        (r"\bheute\b", lambda m: today),
        # „morgen früh“ = morgen; „heute morgen“ fängt die Regel davor ab
        (r"\bmorgen\b", lambda m: today + dt.timedelta(days=1)),
        (rf"\b(?:am |nächsten |am nächsten |kommenden |am kommenden )?({'|'.join(WEEKDAYS)})\b",
         lambda m: _next_weekday(today, WEEKDAYS.index(m[1]))),
        (rf"\bam ({_NUM}\.?) ({'|'.join(_MONTH_ALIASES)})\b", lambda m: _day_month(today, m[1], m[2])),
        (rf"\bam ({_NUM}\.?) ({_NUM}\.?)(?=\s|$)", lambda m: _day_month(today, m[1], m[2])),
    ]
    for pat, conv in rules:
        for m in re.finditer(pat, s):
            d = conv(m)  # type: ignore[operator]
            if d is not None:
                return d, s[: m.start()] + " " + s[m.end():]
    return None, s


def _next_weekday(today: dt.date, wd: int) -> dt.date:
    """Gleicher Wochentag wie heute = nächste Woche (wie im Alltag gemeint)."""
    days = (wd - today.weekday()) % 7 or 7
    return today + dt.timedelta(days=days)


def _day_month(today: dt.date, day_raw: str, month_raw: str) -> dt.date | None:
    day = ordinal_to_int(day_raw)
    month = _MONTH_ALIASES.get(month_raw.rstrip(".")) or ordinal_to_int(month_raw)
    if not day or not month or not 1 <= month <= 12:
        return None
    for year in range(today.year, today.year + 5):  # 29. Februar → nächstes Schaltjahr
        try:
            d = dt.date(year, month, day)
        except ValueError:
            if not (month == 2 and day == 29):
                return None
            continue
        if d >= today:
            return d
    return None


def _parse_daypart(s: str) -> tuple[tuple[str, int] | None, str]:
    for phrase in sorted(_DAYPARTS, key=len, reverse=True):
        m = re.search(rf"\b{phrase}\b", s)
        if m:
            return _DAYPARTS[phrase], s[: m.start()] + " " + s[m.end():]
    return None, s


def _content(rest: str) -> str | None:
    """Inhalt: was nach „an/ans/daran/dass“ steht – sonst, was übrig bleibt (ohne Füllwörter)."""
    rest = re.sub(r"\s+", " ", rest).strip(" ,.")
    m = re.search(r"(?:^|\s)(?:daran|dran|an|ans|dass)\s+(.+)$", rest)
    text = m[1] if m else " ".join(w for w in rest.split() if w not in _FILLER)
    text = re.sub(r"\b(bitte|gell)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.")
    if not text or text in _FILLER:
        return None
    return text[:MAX_TEXT]


def _original_case(content: str | None, original: str) -> str | None:
    """Inhalt in der Schreibweise, wie Alexa ihn erkannt hat („den Arzt“ statt „den arzt“)."""
    if not content:
        return content
    words = content.split()
    m = re.search(r"\W+".join(re.escape(w) for w in words), original, flags=re.IGNORECASE)
    return m[0] if m else content


def parse(text: str, now: dt.datetime, tz: str = "Europe/Vienna") -> Draft:
    """Zerlegt einen freien Satz in Datum, Uhrzeit und Inhalt. Fehlendes bleibt None."""
    local = now.astimezone(ZoneInfo(tz))
    s = " " + fold(text).replace(",", " ") + " "
    s = re.sub(r"^\s*(erinner|erinnere)( mich| uns)?\b", " ", s)
    s = re.sub(r"\b(eine )?erinnerung (für|fuer|an)?\b", " ", s)
    rel, s = _parse_relative(s)
    if isinstance(rel, dt.timedelta):
        # In UTC rechnen: „in zwei Stunden“ in der Umstellungsnacht sind echte zwei Stunden
        when = (now.astimezone(dt.UTC) + rel).astimezone(local.tzinfo).replace(second=0, microsecond=0)
        return Draft(date=when.date().isoformat(), time=f"{when:%H:%M}", text=_original_case(_content(s), text),
                     pm_hint=when.hour >= 12, at=when.astimezone(dt.UTC).isoformat())
    s = re.sub(r"\bheute morgen\b", " heute in der früh ", s)
    s = re.sub(r"\bmorgen früh\b", " morgen in der früh ", s)
    date: dt.date | None
    if isinstance(rel, int):
        date = local.date() + dt.timedelta(days=rel)
    else:
        date, s = _parse_date(s, local.date())
    clock, s = _parse_clock(s)
    daypart, s = _parse_daypart(s)
    draft = Draft(date=date.isoformat() if date else None, text=_original_case(_content(s), text))
    if clock is None and daypart is not None:
        clock = (daypart[1], 0)
    if clock is not None:
        h, m = clock
        kind = daypart[0] if daypart else None
        if h == 24 or (kind == "night" and h == 12 and m == 0):  # Mitternacht = 0 Uhr des Folgetags
            base = date or local.date()
            draft.date = (base + dt.timedelta(days=1)).isoformat()
            h = 0
        elif (kind == "pm" and h < 12) or (kind == "night" and 6 <= h < 12):
            h += 12
        draft.time = f"{h:02d}:{m:02d}"
        if kind is not None or h == 0 or h >= 13:
            draft.pm_hint = h >= 12  # eindeutig
    return draft


@dataclass(frozen=True)
class Resolved:
    when: dt.datetime  # mit Zeitzone (Wien)
    in_past: bool


def resolve(draft: Draft, now: dt.datetime, tz: str = "Europe/Vienna") -> Resolved | None:
    """Fertiger Zeitpunkt aus Datum + Uhrzeit. None, wenn die Uhrzeit fehlt.

    Mehrdeutige Uhrzeit (keine Tageszeit genannt): 1–5 Uhr meint nachmittags. Ohne Datum und schon vorbei →
    dieselbe Uhrzeit am Abend, falls die heute noch kommt („um acht“ um 9 Uhr früh = 20 Uhr), sonst morgen
    („um sieben in der Früh“ am Abend gesagt = morgen 7 Uhr). Nur mit ausdrücklichem Datum („heute um sieben
    in der Früh“) gilt eine vergangene Zeit als vorbei → Ablehnung."""
    if not draft.time:
        return None
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    if draft.at:
        when_at = dt.datetime.fromisoformat(draft.at).astimezone(zone)
        return Resolved(when=when_at, in_past=when_at <= local)
    h, m = (int(x) for x in draft.time.split(":"))
    if draft.pm_hint is None and 1 <= h <= 5:
        h += 12
    day = dt.date.fromisoformat(draft.date) if draft.date else local.date()
    when = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=zone)
    # Nicht existierende/doppelte Uhrzeiten bei der Zeitumstellung: über UTC normalisieren
    when = when.astimezone(dt.UTC).astimezone(zone)
    if when <= local and not draft.date:
        later = when + dt.timedelta(hours=12)
        if draft.pm_hint is None and h < 12 and later > local:
            when = later
        else:
            nxt = day + dt.timedelta(days=1)
            when = dt.datetime(nxt.year, nxt.month, nxt.day, h, m, tzinfo=zone).astimezone(dt.UTC).astimezone(zone)
    return Resolved(when=when, in_past=when <= local)


def spoken_when(when: dt.datetime, now: dt.datetime) -> str:
    """„morgen, Dienstag, um 10 Uhr“ / „heute um 14 Uhr 30“ / „am Freitag, dem 6. November, um 9 Uhr“."""
    local_now = now.astimezone(when.tzinfo)
    days = (when.date() - local_now.date()).days
    clock = f"um {when.hour} Uhr" + (f" {when.minute}" if when.minute else "")
    if when.hour == 0 and when.minute == 0:
        clock = "um Mitternacht"
    weekday = WEEKDAY_NAMES[when.weekday()]
    if days == 0:
        return f"heute {clock}"
    if days == 1:
        return f"morgen, {weekday}, {clock}"
    if days == 2:
        return f"übermorgen, {weekday}, {clock}"
    year = f" {when.year}" if when.year != local_now.year else ""
    return f"am {weekday}, dem {when.day}. {MONTH_NAMES[when.month - 1]}{year}, {clock}"


def from_slots(date_slot: str, time_slot: str, duration_slot: str, now: dt.datetime,
               tz: str = "Europe/Vienna") -> Draft:
    """Werte der eingebauten Slots AMAZON.DATE / AMAZON.TIME / AMAZON.DURATION übernehmen."""
    local = now.astimezone(ZoneInfo(tz))
    if duration_slot:
        m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", duration_slot.strip())
        if m and any(m.groups()):
            delta = dt.timedelta(days=int(m[1] or 0), hours=int(m[2] or 0), minutes=int(m[3] or 0))
            when = (now.astimezone(dt.UTC) + delta).astimezone(local.tzinfo).replace(second=0, microsecond=0)
            return Draft(date=when.date().isoformat(), time=f"{when:%H:%M}", pm_hint=when.hour >= 12,
                         at=when.astimezone(dt.UTC).isoformat())
    draft = Draft()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_slot or ""):
        draft.date = date_slot
    t = (time_slot or "").strip().upper()
    if re.fullmatch(r"\d{2}:\d{2}", t):
        draft.time = t
        draft.pm_hint = True if int(t[:2]) >= 12 else None
    elif t in ("MO", "AF", "EV", "NI"):
        hour = {"MO": 8, "AF": 15, "EV": 19, "NI": 21}[t]
        draft.time, draft.pm_hint = f"{hour:02d}:00", t != "MO"
    return draft
