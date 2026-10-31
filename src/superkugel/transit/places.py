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
OTHER_TOWN_M = 40_000  # gleichnamige Orte weiter auseinander → nachfragen („Meinst du … in Tirol?“)
CENTER_M = 15_000  # Stadtzentrum: wichtigste Bushaltestelle des Heimatorts in diesem Umkreis

# „Bergdorf bei Teststadt“, „Sankt Johann in Tirol“: Zusatz nur als Auswahlhilfe (nächster Treffer dazu)
_HINT = re.compile(r"^(.+?)\s+(?:bei|nahe|naehe|neben|in|im|an der|am)\s+(.+)$")
# Bundesländer als Auswahlhilfe: ungefähre Mitte (allgemeines Wissen, nichts Persönliches)
_REGIONS = {
    "tirol": (47.25, 11.35), "nordtirol": (47.3, 11.3), "osttirol": (46.85, 12.6), "vorarlberg": (47.25, 9.9),
    "salzburg": (47.4, 13.1), "kaernten": (46.72, 14.05), "steiermark": (47.25, 15.0),
    "oberoesterreich": (48.1, 14.0), "niederoesterreich": (48.2, 15.7), "wien": (48.21, 16.37),
    "burgenland": (47.5, 16.45),
}
# Einrichtungen, die im Fahrplan anders heißen („Krankenhaus“ → „LKH“)
_SYNONYMS = {
    "krankenhaus": ("lkh", "klinikum", "krankenhaus", "spital", "ukh"),
    "spital": ("lkh", "klinikum", "krankenhaus", "spital"),
    "klinik": ("lkh", "klinikum", "klinik"),
    "schwimmbad": ("bad", "hallenbad", "freibad", "strandbad"),
    "rathaus": ("rathaus", "stadtamt", "gemeindeamt"),
}
# „in die Stadt“, „ins Zentrum“ (vom Satz oder von der KI): Zentrum des Heimatorts
CENTER_WORDS = {"stadtzentrum", "zentrum", "innenstadt", "stadt", "stadtmitte", "ortszentrum", "ortsmitte",
                "city", "hauptplatz"}

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
    others: tuple[str, ...] = ()  # gleichnamige Orte anderswo (Bereichs-IDs) → erst nachfragen


class PlaceIndex:
    """Haltestellenverzeichnis für die Suche nach gesprochenen Namen."""

    def __init__(self, tt: Timetable, aliases: dict[str, str] | None = None, home_gid: str = "") -> None:
        self.tt = tt
        home = tt.by_gid.get(home_gid) if home_gid else None
        self.home_idx = home
        self.home = (tt.areas[home].lat, tt.areas[home].lon) if home is not None else None
        self.norm = [_norm(a.name) for a in tt.areas]
        self.tokens = [[w for w in n.split() if w not in _STOPWORDS] for n in self.norm]  # „Sankt Johann in Tirol“ ohne „in“
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

    def center(self) -> Place | None:
        """„in die Stadt“: die Bushaltestelle des Heimatorts mit den meisten Abfahrten (aus den Daten, nicht fest)."""
        if self.home_idx is None or not self.home or not self.tokens[self.home_idx]:
            return None
        from superkugel.transit.build import _meters

        town = self.tokens[self.home_idx][0]
        areas = self.tt.areas
        pool = [i for i, toks in enumerate(self.tokens) if toks and toks[0] == town and not areas[i].rail
                and _meters(*self.home, areas[i].lat, areas[i].lon) <= CENTER_M]
        return self._area_place(max(pool, key=lambda i: areas[i].weight)) if pool else None

    def find(self, said: str, rail: bool = False, strict: bool = False) -> Place | None:
        """Bester Treffer für „Graz“, „Linz Hauptbahnhof“, „Marktplatz“ (ohne Ort: der nächstgelegene) …

        Tolerant: Zusätze wie „bei Teststadt“ oder „in Tirol“ wählen nur unter gleichnamigen Orten aus; folgen dem
        Namen weitere Wörter („Bergdorf zu meiner Schwester“), zählt der längste bekannte Anfang.
        ``strict``: nur ganze Wörter, keine Annäherung (für Sätze, die ohne KI als Fahrplanfrage gelten sollen)."""
        q = [w for w in _norm(said).split() if w not in _STOPWORDS]
        if not q:
            return None
        if alias := self._alias(q):
            return alias
        self._whole = strict
        if cands := self._candidates(q):
            return self._pick(q, cands, rail)
        if (m := _HINT.match(_norm(said))) and (near := self._hint_point(m.group(2))):
            base = [w for w in m.group(1).split() if w not in _STOPWORDS]
            if base and (alias := self._alias(base)):
                return alias
            if base and not self._candidates(base) and not strict:
                base = self._fix(base)
            if base and (cands := self._candidates(base)):
                return self._pick(base, cands, rail, near=near)
        for n in range(len(q) - 1, 0, -1):  # Kurzname mitten im Satz: längster Anfang, der ein Ort ist
            if alias := self._alias(q[:n]):
                return alias
            if cands := self._candidates(q[:n]):
                return self._pick(q[:n], cands, rail)
        if strict:
            return None
        fixed = self._fix(q)  # Erkennungsfehler: Wörter an den Wortschatz annähern („Klagenfort“)
        if fixed != q and (cands := self._candidates(fixed)):
            return self._pick(fixed, cands, rail)
        return None

    def _alias(self, q: list[str]) -> Place | None:
        gid = self.aliases.get(" ".join(q))
        return self.by_gid(gid) if gid else None

    def _fix(self, q: list[str]) -> list[str]:
        return [(difflib.get_close_matches(w, self.vocab, n=1, cutoff=0.78) or [w])[0] for w in q]

    def _hint_point(self, hint: str) -> tuple[float, float] | None:
        words = [w for w in plain(hint).split() if w not in _STOPWORDS]
        if not words:
            return None
        if " ".join(words) in _REGIONS:
            return _REGIONS[" ".join(words)]
        p = self.find(" ".join(words))
        if p is None:
            return None
        a = self.tt.areas[min(p.areas)]
        return a.lat, a.lon

    def _pick(self, q: list[str], cands: list[int], rail: bool, near: tuple[float, float] | None = None) -> Place:
        from superkugel.transit.build import _meters

        areas = self.tt.areas
        if near:  # Auswahlhilfe: unter den Treffern der Ort, der dem Zusatz am nächsten ist
            best = min(cands, key=lambda i: _meters(*near, areas[i].lat, areas[i].lon))
            cands = [i for i in cands
                     if _meters(areas[best].lat, areas[best].lon, areas[i].lat, areas[i].lon) <= OTHER_TOWN_M / 4]
        exact = [i for i in cands if self.tokens[i] == q]
        if exact:
            return self._area_place(max(exact, key=lambda i: areas[i].weight))
        # Ortsname („Klagenfurt“): Name beginnt mit den Suchwörtern → Bahnhof bevorzugen, sonst wichtigste Haltestelle
        town = [i for i in cands if self.tokens[i][:len(q)] == q]
        pool = town or cands
        rail_pool = [i for i in pool if areas[i].rail]
        if town and not near and not self._near_home(town) and (reps := self._other_towns(town)):
            # gleichnamige Orte weit auseinander, keiner in der Nähe: den wichtigsten nehmen, aber nachfragen
            p = self._area_place(self._town_pick(reps[0], town))
            return Place(p.areas, p.name, others=tuple(areas[self._town_pick(r, town)].gid for r in reps[1:4]))
        if town and rail_pool:
            return self._area_place(self._town_pick(None, rail_pool))
        if rail and rail_pool:
            pool = rail_pool
        if not town and self.home:  # „zum Hauptbahnhof“, „Marktplatz“: die nächstgelegene ist gemeint
            def dist(i: int) -> float:
                return _meters(*self.home, areas[i].lat, areas[i].lon)

            close = [i for i in pool if dist(i) <= NEAR_M]
            if close:  # grob die nächste, dabei wenigste Zusatzwörter („Marktplatz“ ≠ „Marktplatz Nord“)
                return self._area_place(min(close, key=lambda i: (dist(i) // 5000, len(self.tokens[i]) - len(q),
                                                                   dist(i))))
        return self._area_place(max(pool, key=lambda i: (areas[i].weight, -len(self.tokens[i]))))

    def _rank(self, i: int) -> tuple:
        """Bahnhof vor Bushaltestelle, Hauptbahnhof zuerst, dann die wichtigste."""
        n, a = self.norm[i], self.tt.areas[i]
        return (a.rail and "hauptbahnhof" in n, a.rail and "bahnhof" in n, a.rail, a.weight)

    def _town_pick(self, around: int | None, pool: list[int]) -> int:
        """Bester Bereich eines Orts; ``around``: nur Bereiche in der Nähe dieses Vertreters."""
        from superkugel.transit.build import _meters

        areas = self.tt.areas
        if around is not None:
            a = areas[around]
            pool = [i for i in pool if _meters(a.lat, a.lon, areas[i].lat, areas[i].lon) <= OTHER_TOWN_M / 2]
        return max(pool, key=self._rank)

    def _other_towns(self, town: list[int]) -> list[int]:
        """Je gleichnamigem Ort ein Vertreter (wichtigster zuerst) – nur wenn es mehrere weit auseinander gibt."""
        from superkugel.transit.build import _meters

        areas = self.tt.areas
        reps: list[int] = []
        for i in sorted(town, key=self._rank, reverse=True):
            if all(_meters(areas[r].lat, areas[r].lon, areas[i].lat, areas[i].lon) > OTHER_TOWN_M for r in reps):
                reps.append(i)
        return reps if len(reps) > 1 else []

    def _near_home(self, idx: list[int]) -> bool:
        from superkugel.transit.build import _meters

        areas = self.tt.areas
        return bool(self.home) and any(_meters(*self.home, areas[i].lat, areas[i].lon) <= NEAR_M for i in idx)

    def _candidates(self, q: list[str]) -> list[int]:
        whole = getattr(self, "_whole", False)
        alts = [_SYNONYMS.get(w, (w,)) for w in q]  # „Krankenhaus“ → auch „LKH …“
        return [i for i, toks in enumerate(self.tokens)
                if all(any(t == s if whole else t.startswith(s) for t in toks for s in alt) for alt in alts)]


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
