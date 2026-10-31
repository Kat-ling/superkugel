"""Haltestellen finden (tolerant, wie gesprochen) und Namen/Verkehrsmittel aussprechbar machen."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from superkugel.language import plain
from superkugel.transit.build import KIND_BUS, KIND_CALL, KIND_SUBWAY, KIND_TRAIN, KIND_TRAM
from superkugel.transit.timetable import Timetable

# Abkürzungen in Haltestellennamen → gesprochen (vor dem Normalisieren angewendet)
_NAME_SUBS = [
    (re.compile(r"\bHbf\b\.?", re.I), "Hauptbahnhof"),
    (re.compile(r"\bBf\b\.?", re.I), "Bahnhof"),
    (re.compile(r"\bBahnhst\b\.?", re.I), "Bahnhaltestelle"),
    (re.compile(r"\bHst\b\.?", re.I), "Haltestelle"),
    (re.compile(r"\bi\.\s*T\.", re.I), "in Tirol"),
    (re.compile(r"\bSt\.\s*(?=[A-ZÄÖÜ])"), "Sankt "),
    (re.compile(r"\bStr\.", re.I), "Straße"),
    (re.compile(r"\bGh\b\.?"), "Gasthof"),
    (re.compile(r"\bKtn\b\.?"), "Kärnten"),
    (re.compile(r"\bb\.\s*(?=[A-ZÄÖÜ])"), "bei "),
    (re.compile(r"\s*\([^)]*\)"), ""),
]
_STOPWORDS = {"der", "die", "das", "den", "dem", "des", "zum", "zur", "zu", "nach", "bis", "von", "vom", "ab", "in",
              "im", "am", "an", "bei", "beim", "richtung", "haltestelle", "station"}

NEAR_M = 30_000  # allgemeine Namen ohne Ort: nächstgelegene Haltestelle in diesem Umkreis
SAME_NAME_M = 1_500  # gleichnamige Bereiche so nah beieinander gelten als ein Ort

# Zuggattungen (Kürzel aus dem Fahrplan) → gesprochen
TRAIN_NAMES = {
    "RJX": "Railjet Express", "RJ": "Railjet", "ICE": "ICE", "IC": "Intercity", "EC": "Eurocity", "EN": "Euronight",
    "NJ": "Nightjet", "IR": "Interregio", "REX": "Regionalexpress", "R": "Regionalzug", "CJX": "Cityjet Express",
    "S": "S-Bahn", "WB": "Westbahn", "D": "Schnellzug", "ER": "Regionalzug", "SP": "Schnellzug", "OS": "Regionalzug",
}


def spoken_name(name: str) -> str:
    for rx, rep in _NAME_SUBS:
        name = rx.sub(rep, name)
    name = name.replace("/", ", ").replace(" - ", ", ")
    return re.sub(r"\s+", " ", name).strip(" ,")


def _norm(name: str) -> str:
    return plain(spoken_name(name).replace("-", " "))


@dataclass(frozen=True)
class Place:
    areas: frozenset[int]
    name: str  # gesprochen
    is_home: bool = False


class PlaceIndex:
    """Haltestellenverzeichnis für die Suche nach gesprochenen Namen."""

    def __init__(self, tt: Timetable, aliases: dict[str, str] | None = None, home_gid: str = "") -> None:
        self.tt = tt
        home = tt.by_gid.get(home_gid) if home_gid else None
        self.home = (tt.areas[home].lat, tt.areas[home].lon) if home is not None else None
        self.norm = [_norm(a.name) for a in tt.areas]
        self.tokens = [n.split() for n in self.norm]
        self.vocab = sorted({w for toks in self.tokens for w in toks})
        self.aliases = {plain(k): v for k, v in (aliases or {}).items()}

    def _area_place(self, idx: int) -> Place:
        """Ein Bereich – plus gleichnamige in der Nähe (Bahnsteige und Busbahnhof haben teils eigene IDs)."""
        from superkugel.transit.build import _meters

        a = self.tt.areas[idx]
        same = {i for i, n in enumerate(self.norm) if n == self.norm[idx]
                and _meters(a.lat, a.lon, self.tt.areas[i].lat, self.tt.areas[i].lon) <= SAME_NAME_M}
        return Place(frozenset(same | {idx}), spoken_name(a.name))

    def by_gid(self, gid: str) -> Place | None:
        idx = self.tt.by_gid.get(gid)
        return self._area_place(idx) if idx is not None else None

    def find(self, said: str, rail: bool = False) -> Place | None:
        """Bester Treffer für „Graz“, „Linz Hauptbahnhof“, „Marktplatz“ (ohne Ort: der nächstgelegene) …"""
        q = [w for w in _norm(said).split() if w not in _STOPWORDS]
        if not q:
            return None
        alias = self.aliases.get(" ".join(q))
        if alias and (p := self.by_gid(alias)):
            return p
        cands = self._candidates(q)
        if not cands:  # Erkennungsfehler: Wörter an den Wortschatz annähern („Klagenfort“)
            fixed = [(difflib.get_close_matches(w, self.vocab, n=1, cutoff=0.78) or [w])[0] for w in q]
            if fixed != q:
                cands = self._candidates(fixed)
                q = fixed
        if not cands:
            return None
        areas = self.tt.areas
        exact = [i for i in cands if self.tokens[i] == q]
        if exact:
            return self._area_place(max(exact, key=lambda i: areas[i].weight))
        # Ortsname („Klagenfurt“): Name beginnt mit den Suchwörtern → Bahnhof bevorzugen, sonst wichtigste Haltestelle
        town = [i for i in cands if self.tokens[i][:len(q)] == q]
        pool = town or cands
        rail_pool = [i for i in pool if areas[i].rail]
        if town and rail_pool:
            def rank(i: int) -> tuple:
                n = self.norm[i]
                return ("hauptbahnhof" in n, "bahnhof" in n, areas[i].weight)
            return self._area_place(max(rail_pool, key=rank))
        if rail and rail_pool:
            pool = rail_pool
        if not town and self.home:  # „zum Hauptbahnhof“, „Marktplatz“: die nächstgelegene ist gemeint
            from superkugel.transit.build import _meters

            def dist(i: int) -> float:
                return _meters(*self.home, areas[i].lat, areas[i].lon)

            close = [i for i in pool if dist(i) <= NEAR_M]
            if close:  # wenigste Zusatzwörter zuerst („Marktplatz“ ≠ „Marktplatz Nord“), dann die nächste
                return self._area_place(min(close, key=lambda i: (len(self.tokens[i]) - len(q), dist(i))))
        return self._area_place(max(pool, key=lambda i: (areas[i].weight, -len(self.tokens[i]))))

    def _candidates(self, q: list[str]) -> list[int]:
        out = []
        for i, toks in enumerate(self.tokens):
            if all(any(t.startswith(w) for t in toks) for w in q):
                out.append(i)
        return out


def vehicle(tt: Timetable, trip: int) -> str:
    """„der Railjet“, „der Bus 160“, „die S-Bahn S1“ – mit Artikel, für „mit dem …“."""
    kind, name, _, _ = tt.trip_info(trip)
    short = tt.routes[tt.trip_route[trip]][1]
    if kind == KIND_TRAIN:
        cat = name.split(" ")[0] if name else ""
        spoken = TRAIN_NAMES.get(cat.upper(), "")
        if cat.upper() == "S" and short.upper().startswith("S") and short[1:].isdigit():
            return f"der S-Bahn {short.upper()}"
        if not spoken:
            return "dem Zug"
        return f"der {spoken}" if spoken in ("S-Bahn", "Westbahn") else f"dem {spoken}"
    if kind == KIND_CALL:
        return "dem Rufbus"
    if kind == KIND_TRAM:
        return f"der Straßenbahn {short}".strip()
    if kind == KIND_SUBWAY:
        return f"der U-Bahn {short}".strip()
    if short.upper().startswith("SV"):
        return "dem Schienenersatzbus"
    if kind == KIND_BUS and short and short.upper() not in ("BUS", "POSTBUS"):
        return f"dem Bus {short}"
    return "dem Bus"


def line_short(tt: Timetable, trip: int) -> str:
    """Für Abfahrtslisten: „Linie 5B“, „Railjet“, „S-Bahn S1“."""
    v = vehicle(tt, trip)
    for art in ("dem ", "der "):
        v = v.removeprefix(art)
    return v.replace("Bus ", "Linie ") if v.startswith("Bus ") else v
