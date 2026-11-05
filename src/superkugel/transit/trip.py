"""Reise-Stand: was im Fahrplan-Gespräch gerade gilt, und wie eine Nachfrage ihn ändert.

Jede Nachfrage ist eine ``Change``: Sie nennt nur, was anders sein soll, alles andere bleibt. So geht bei „gegen zehn“
der Tag nicht verloren. ``merge`` rechnet ohne KI, Fahrplan und Sitzung; die Antwort berechnet danach ``service.answer``.
Der Stand liegt in der Sitzung und 30 Minuten beim Gesprächseintrag (übersteht „Stopp“), nie im Log.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from typing import Any

DAY_S = 86_400
MAX_DAYS_AHEAD = 370
PAST_TOLERANCE_S = 1800  # wie ask._parse_time: Uhrzeit vor mehr als 30 Minuten gilt als „heute schon vorbei“


@dataclass
class Spot:
    """Ein Ort. ``gid`` leer = nur gesagt, noch nicht im Fahrplan gefunden. ``home`` = zu Hause."""
    gid: str = ""
    name: str = ""
    home: bool = False


@dataclass
class Trip:
    origin: Spot = field(default_factory=Spot)
    dest: Spot | None = None  # None = nur Abfahrten
    day: str = ""  # ISO-Datum
    time_s: int | None = None  # None = ab jetzt bzw. ab Betriebsbeginn
    mode: str = "any"  # any | bus | train
    last: bool = False
    day_said: bool = False  # Tag wurde genannt und bleibt, auch wenn eine Uhrzeit heute schon vorbei wäre
    dep: int | None = None  # zuletzt genannte Fahrt
    arr: int | None = None
    short: bool = False  # zuletzt nur die Kurzfassung gesagt („genauer“ möglich)
    open: str = ""  # "day": Tag ist unklar, "dest": Ziel fehlt
    text: str = ""  # bei offenem Tag: die Frage, die der Tag ergänzt

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Trip | None:
        """Aus den Sitzungsattributen; unbrauchbare Daten gelten als „kein Stand“."""
        if not isinstance(data, dict) or not isinstance(data.get("origin"), dict):
            return None
        known = {f.name for f in dataclasses.fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        values["origin"] = _spot(data["origin"])
        values["dest"] = _spot(data["dest"]) if isinstance(data.get("dest"), dict) else None
        for name in ("time_s", "dep", "arr"):  # DynamoDB liefert Zahlen als Decimal
            if values.get(name) is not None:
                values[name] = int(values[name])
        return cls(**values)

    def chosen(self) -> dict[str, str]:
        """Bereits gefundene Orte je Rolle (Bereichs-IDs) – so entfällt eine neue Suche oder Rückfrage."""
        out = {"origin": self.origin.gid} if self.origin.gid else {}
        if self.dest and self.dest.gid:
            out["dest"] = self.dest.gid
        return out


@dataclass
class Change:
    """Was eine Nachfrage ändert. Leere Felder bleiben, wie sie sind."""
    action: str  # aendern | rueckfahrt | spaeter | frueher | genauer | abfahrten
    start: str = ""
    ziel: str = ""
    naehe: str = ""
    tag: str = ""  # ISO-Datum
    zeit_s: int | None = None
    bezug: str = "absolut"  # absolut | nach_ankunft | nach_abfahrt
    versatz_min: int = 0
    mode: str = ""
    last: bool | None = None


def _spot(data: dict[str, Any]) -> Spot:
    return Spot(str(data.get("gid", "")), str(data.get("name", "")), bool(data.get("home", False)))


def _valid_day(tag: str, today: dt.date) -> bool:
    try:
        day = dt.date.fromisoformat(tag)
    except ValueError:
        return False
    return today <= day <= today + dt.timedelta(days=MAX_DAYS_AHEAD)


def _apply_common(t: Trip, c: Change) -> None:
    if c.mode:
        t.mode = c.mode
    if c.last is not None:
        t.last = c.last
    if c.tag:
        t.day, t.day_said = c.tag, True


def _return_time(t: Trip, c: Change, base: Trip) -> None:
    """Rückfahrt: genannte Zeit, sonst Abstand zur letzten Fahrt; nach Mitternacht zählt der nächste Tag."""
    anchor = {"nach_ankunft": base.arr, "nach_abfahrt": base.dep}.get(c.bezug)
    if c.zeit_s is not None:
        t.time_s = c.zeit_s
    elif c.tag or anchor is None:
        t.time_s = None
    else:
        secs = int(anchor) + c.versatz_min * 60
        if secs >= DAY_S:
            t.day = (dt.date.fromisoformat(t.day) + dt.timedelta(days=1)).isoformat()
            secs -= DAY_S
        t.time_s = secs


def merge(trip: Trip, change: Change, today: dt.date, now_s: int = 0) -> Trip:
    """Neuer Stand aus altem Stand und Änderung; der alte bleibt unberührt. ``open`` meldet, was noch fehlt."""
    t = dataclasses.replace(trip, dep=None, arr=None, short=False, open="", text="")
    if change.tag and not _valid_day(change.tag, today):
        t.open = "day"
        return t
    a = change.action
    if a == "rueckfahrt":
        if not trip.dest:
            t.open = "dest"
            return t
        t.origin, t.dest, t.last = trip.dest, trip.origin, False
        _apply_common(t, change)
        _return_time(t, change, trip)
        return t
    _apply_common(t, change)
    if a in ("spaeter", "frueher", "genauer"):
        dep = trip.dep or 0
        t.time_s = {"spaeter": dep + 60, "frueher": max(0, dep - 3600), "genauer": dep}[a]
        t.last = False
    elif a == "abfahrten":
        t.dest = None
    if change.start:
        t.origin = Spot(name=change.start)
    if change.ziel:
        t.dest = Spot(name=f"{change.ziel} bei {change.naehe}" if change.naehe else change.ziel)
    if change.zeit_s is not None:
        t.time_s = change.zeit_s
        if change.last is None:
            t.last = False
        if not t.day_said and t.day == today.isoformat() and change.zeit_s < now_s - PAST_TOLERANCE_S:
            t.day = (today + dt.timedelta(days=1)).isoformat()  # kein Tag genannt, Uhrzeit heute vorbei
    return t


def trip_text(trip: Trip) -> str:
    """Stand als Satz für den Fahrplan-Leser (Rückfrage „Meinst du …?“, offener Tag)."""
    mode = {"train": "zug", "bus": "bus"}.get(trip.mode, "")
    dest = f"nach {trip.dest.name}" if trip.dest else ""
    return " ".join(x for x in (mode, f"von {trip.origin.name}", dest) if x)
