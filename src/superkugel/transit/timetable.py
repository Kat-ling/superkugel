"""Fahrplanpaket im Speicher + Abfahrten + Verbindungssuche (Connection Scan, vorwärts und rückwärts).

Zeiten sind Sekunden ab Mitternacht des Betriebstags (GTFS: auch über 24 Uhr). Eine Suche schaut immer auch auf den
Vortag (Fahrten nach Mitternacht) und – spät abends – auf den Folgetag.
"""

from __future__ import annotations

import array
import bisect
import datetime as dt
import io
import json
import zipfile
from collections import defaultdict
from dataclasses import dataclass

DAY = 86_400
CHANGE_S = 300  # Umsteigezeit am selben Haltestellenbereich – großzügig für ältere Fahrgäste (eigene Annahme)
INF = 1 << 40


@dataclass(frozen=True)
class Area:
    idx: int
    gid: str
    name: str
    lat: float
    lon: float
    weight: int
    rail: bool


@dataclass(frozen=True)
class Leg:
    """Ein Fahrtabschnitt (oder Fußweg, dann ``trip`` = -1). Zeiten in Sekunden ab Mitternacht des Abfragetags."""

    frm: int
    to: int
    dep: int
    arr: int
    trip: int = -1


@dataclass(frozen=True)
class Departure:
    dep: int  # Sekunden ab Mitternacht des Abfragetags
    trip: int
    area: int


class Timetable:
    def __init__(self, data: bytes) -> None:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            def arr(name: str, code: str = "i") -> array.array:
                a = array.array(code)
                a.frombytes(z.read(name))
                return a

            self.meta = json.loads(z.read("meta.json"))
            self.start = dt.date.fromisoformat(self.meta["start"])
            self.end = dt.date.fromisoformat(self.meta["end"])
            self.ndays = int(self.meta["days"])
            self.areas = [Area(i, *row[:5], bool(row[5])) for i, row in enumerate(json.loads(z.read("areas.json")))]
            self.routes = [tuple(r) for r in json.loads(z.read("routes.json"))]
            self.strings = json.loads(z.read("strings.json"))
            self.flex = json.loads(z.read("flex.json"))
            self.services = z.read("services.bin")
            self.trip_route, self.trip_service = arr("trip_route.bin"), arr("trip_service.bin")
            self.trip_head, self.trip_name = arr("trip_head.bin"), arr("trip_name.bin")
            self.dep, self.arr, self.frm = arr("conn_dep.bin"), arr("conn_arr.bin"), arr("conn_frm.bin")
            self.to, self.trip = arr("conn_to.bin"), arr("conn_trip.bin")
            self.flags = z.read("conn_flags.bin")
            self.by_arr, self.arr_sorted = arr("conn_by_arr.bin"), arr("conn_arr_sorted.bin")
            fa, fb, fs = arr("foot_a.bin"), arr("foot_b.bin"), arr("foot_s.bin")
        self.foot: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for a, b, s in zip(fa, fb, fs, strict=True):
            self.foot[a].append((b, s))
        self.area_flex: dict[int, list[int]] = defaultdict(list)
        for i, f in enumerate(self.flex):
            for a in f["areas"]:
                self.area_flex[a].append(i)
        self.by_gid = {a.gid: a.idx for a in self.areas}
        # Abfahrten je Haltestellenbereich (für „nächster Bus“), nach Zeit sortiert
        self._dep_index: dict[int, array.array] | None = None
        self._active: dict[dt.date, bytearray] = {}
        self._active_k: dict[tuple[dt.date, frozenset[int]], bytearray] = {}

    # ------------------------------------------------------------------ Kalender
    def covers(self, day: dt.date) -> bool:
        return self.start <= day <= self.end

    def active(self, day: dt.date) -> bytearray:
        """1 je Fahrt, die an diesem Betriebstag verkehrt (zwischengespeichert, max. 4 Tage)."""
        if day in self._active:
            return self._active[day]
        out = bytearray(len(self.trip_service))
        if self.covers(day):
            off, nd, svc = (day - self.start).days, self.ndays, self.services
            on = {s for s in set(self.trip_service) if svc[s * nd + off]}
            ts = self.trip_service
            for t in range(len(ts)):
                if ts[t] in on:
                    out[t] = 1
        if len(self._active) >= 4:
            self._active.pop(next(iter(self._active)))
        self._active[day] = out
        return out

    def active_for(self, day: dt.date, kinds: frozenset[int] | None) -> bytearray:
        """Wie ``active``, aber nur Fahrten bestimmter Arten (z. B. nur Züge)."""
        act = self.active(day)
        if kinds is None:
            return act
        key = (day, kinds)
        if key not in self._active_k:
            mask = bytes(1 if self.routes[r][0] in kinds else 0 for r in range(len(self.routes)))
            tr = self.trip_route
            self._active_k = {k: v for k, v in self._active_k.items() if k[0] == day}
            self._active_k[key] = bytearray(a & mask[tr[i]] for i, a in enumerate(act))
        return self._active_k[key]

    # ------------------------------------------------------------------ Abfahrten
    def departures(self, areas: set[int], day: dt.date, t: int, limit: int = 3, window_s: int = 4 * 3600,
                   kinds: frozenset[int] | None = None) -> list[Departure]:
        """Nächste Abfahrten ab ``t`` (Sekunden des Tags ``day``) an einem der Bereiche – eine je Fahrt."""
        out: list[Departure] = []
        seen: set[tuple[int, int]] = set()
        for shift, d in ((DAY, day - dt.timedelta(days=1)), (0, day), (-DAY, day + dt.timedelta(days=1))):
            lo_t, hi_t = t + shift, t + shift + window_s
            if hi_t < 0 or lo_t > 2 * DAY:
                continue
            act = self.active(d)
            lo = bisect.bisect_left(self.dep, lo_t)
            hi = bisect.bisect_right(self.dep, hi_t)
            for i in range(lo, hi):
                if self.frm[i] in areas and act[self.trip[i]] and not self.flags[i] & 1:
                    tr = self.trip[i]
                    if (shift, tr) in seen:
                        continue
                    if kinds is not None and self.routes[self.trip_route[tr]][0] not in kinds:
                        continue
                    seen.add((shift, tr))
                    out.append(Departure(self.dep[i] - shift, tr, self.frm[i]))
        out.sort(key=lambda x: x.dep)
        return out[:limit]

    # ------------------------------------------------------------------ Verbindungssuche
    def _streams(self, day: dt.date, t_lo: int, t_hi: int, times: array.array,
                 kinds: frozenset[int] | None = None) -> list[tuple[int, bytearray]]:
        """(Verschiebung, aktive Fahrten) für Vortag/Tag/Folgetag – nur, wenn es dort im Fenster Fahrten gibt."""
        out = []
        first, last = times[0], times[-1]
        for shift, d in ((DAY, day - dt.timedelta(days=1)), (0, day), (-DAY, day + dt.timedelta(days=1))):
            if t_hi + shift >= first and t_lo + shift <= last:
                out.append((shift, self.active_for(d, kinds)))
        return out

    def corridor(self, sources: set[int], targets: set[int], factor: float = 1.5, extra_m: float = 25_000) -> bytearray:
        """Bereiche, über die ein sinnvoller Weg führen kann (Ellipse um Start und Ziel) – spart Rechenzeit."""
        from superkugel.transit.build import _meters

        areas = self.areas
        pts_s = [(areas[s].lat, areas[s].lon) for s in sources]
        pts_t = [(areas[t].lat, areas[t].lon) for t in targets]
        direct = min(_meters(*a, *b) for a in pts_s for b in pts_t)
        limit = direct * factor + extra_m
        out = bytearray(len(areas))
        for a in areas:
            ds = min(_meters(a.lat, a.lon, *p) for p in pts_s)
            dt_ = min(_meters(a.lat, a.lon, *p) for p in pts_t)
            if ds + dt_ <= limit:
                out[a.idx] = 1
        for x in (*sources, *targets):
            out[x] = 1
        return out

    def earliest_arrival(self, sources: dict[int, int], targets: set[int], day: dt.date, allowed: bytearray,
                         horizon_s: int = 14 * 3600, kinds: frozenset[int] | None = None) -> int | None:
        """Früheste Ankunft an einem Ziel (Sekunden des Tags) oder None (Vorwärts-Scan)."""
        t0 = min(sources.values())
        best = INF
        ready: dict[int, int] = {}
        for a, t in sources.items():
            ready[a] = min(ready.get(a, INF), t)
            for b, s in self.foot.get(a, ()):
                ready[b] = min(ready.get(b, INF), t + s)
        for a in targets:
            best = min(best, ready.get(a, INF))
        dep, arr, frm, to, trip, flags, foot = self.dep, self.arr, self.frm, self.to, self.trip, self.flags, self.foot
        ntrips = len(self.trip_service)
        streams = self._streams(day, t0, t0 + horizon_s, dep, kinds)
        limit = t0 + horizon_s

        def visit(i: int, sh: int, act: bytearray, bk: bytearray) -> None:
            nonlocal best
            tr = trip[i]
            if not act[tr] or not allowed[frm[i]]:
                return
            if not bk[tr]:
                if flags[i] & 1 or ready.get(frm[i], INF) > dep[i] - sh:
                    return
                bk[tr] = 1
            if flags[i] & 2:
                return
            a_t = arr[i] - sh
            b = to[i]
            if b in targets and a_t < best:
                best = a_t
            r = a_t + CHANGE_S
            if r < ready.get(b, INF):
                ready[b] = r
                for c, s in foot.get(b, ()):
                    if a_t + s < ready.get(c, INF):
                        ready[c] = a_t + s
                        if c in targets and a_t + s < best:
                            best = a_t + s

        # Hauptstrom (der Tag selbst) in einer schnellen Schleife; Vortag/Folgetag (Fahrten über Mitternacht) sind
        # wenige Verbindungen – vorab einsammeln und an der richtigen Stelle einschieben.
        main = next(((s, a) for s, a in streams if s == 0), streams[0] if streams else None)
        if main is None:
            return None
        pending = sorted((dep[i] - s, i, s, a, bk) for s, a in streams if (s, a) != main
                         for bk in (bytearray(ntrips),)
                         for i in range(bisect.bisect_left(dep, t0 + s), bisect.bisect_right(dep, limit + s)))
        pi, next_p = 0, (pending[0][0] if pending else INF)
        sh, act = main
        bk = bytearray(ntrips)
        get = ready.get
        for i in range(bisect.bisect_left(dep, t0 + sh), len(dep)):
            d = dep[i] - sh
            while next_p <= d:
                visit(*pending[pi][1:])
                pi += 1
                next_p = pending[pi][0] if pi < len(pending) else INF
            if d > best or d > limit:
                break
            tr = trip[i]
            if not act[tr]:
                continue
            f = frm[i]
            if not allowed[f]:
                continue
            if not bk[tr]:
                if flags[i] & 1 or get(f, INF) > d:
                    continue
                bk[tr] = 1
            if flags[i] & 2:
                continue
            a_t = arr[i] - sh
            b = to[i]
            if a_t < best and b in targets:
                best = a_t
            if a_t + CHANGE_S < get(b, INF):
                ready[b] = a_t + CHANGE_S
                for c, s in foot.get(b, ()):
                    if a_t + s < get(c, INF):
                        ready[c] = a_t + s
                        if c in targets and a_t + s < best:
                            best = a_t + s
        while pi < len(pending) and pending[pi][0] <= min(best, limit):
            visit(*pending[pi][1:])
            pi += 1
        return None if best >= INF else best

    def latest_journey(self, sources: set[int], targets: set[int], day: dt.date, deadline: int,
                       not_before: int, allowed: bytearray, kinds: frozenset[int] | None = None) -> list[Leg] | None:
        """Späteste Abfahrt an einer Quelle, mit der man bis ``deadline`` ein Ziel erreicht (Rückwärts-Scan)."""
        dep, frm, to, trip, flags, by_arr = self.dep, self.frm, self.to, self.trip, self.flags, self.by_arr
        arr_sorted, foot = self.arr_sorted, self.foot
        latest: dict[int, int] = {}  # spätester Zeitpunkt, an dem man dort sein muss
        jp: dict[int, tuple] = {}  # Bereich → ('ride', Einstieg, Ausstieg, Verschiebung) | ('walk', Ziel, s) | ('end',)
        for t in targets:
            latest[t], jp[t] = deadline, ("end",)
        for t in targets:
            for c, s in foot.get(t, ()):
                if c not in targets and deadline - s > latest.get(c, -INF):
                    latest[c], jp[c] = deadline - s, ("walk", t, s)
        streams = self._streams(day, not_before, deadline, arr_sorted, kinds)
        best_src = max((latest.get(s, -INF) for s in sources), default=-INF)

        def visit(p: int, sh: int, act: bytearray, exits: dict[int, int]) -> None:
            nonlocal best_src
            i = by_arr[p]
            tr = trip[i]
            if not act[tr] or not allowed[frm[i]]:
                return
            d_t = dep[i] - sh
            if d_t < not_before:
                return
            ex = exits.get(tr)
            if ex is None and not flags[i] & 2:
                b = to[i]
                need = latest.get(b, -INF)
                # Umsteigezeit nur beim Wechsel in eine andere Fahrt am selben Ort (Fußweg/Ziel: wie vorwärts ohne)
                slack = CHANGE_S if jp.get(b, ("end",))[0] == "ride" else 0
                if need > -INF and arr_sorted[p] - sh + slack <= need:
                    ex = exits[tr] = i
            if ex is None or flags[i] & 1:
                return
            a = frm[i]
            if d_t > latest.get(a, -INF):
                latest[a], jp[a] = d_t, ("ride", i, ex, sh)
                if a in sources and d_t > best_src:
                    best_src = d_t
                for c, s in foot.get(a, ()):
                    if c not in targets and d_t - s > latest.get(c, -INF):
                        latest[c], jp[c] = d_t - s, ("walk", a, s)
                        if c in sources and d_t - s > best_src:
                            best_src = d_t - s

        main = next(((s, a) for s, a in streams if s == 0), streams[0] if streams else None)
        if main is None:
            return None
        pending = sorted(((arr_sorted[p] - s, p, s, a, ex) for s, a in streams if (s, a) != main
                          for ex in ({},)
                          for p in range(bisect.bisect_left(arr_sorted, not_before + s),
                                         bisect.bisect_right(arr_sorted, deadline + s))), key=lambda x: (-x[0], -x[1]))
        pi, next_p = 0, (pending[0][0] if pending else -INF)
        sh, act = main
        exits: dict[int, int] = {}
        for p in range(bisect.bisect_right(arr_sorted, deadline + sh) - 1, -1, -1):
            a_time = arr_sorted[p] - sh
            while next_p >= a_time:
                visit(*pending[pi][1:])
                pi += 1
                next_p = pending[pi][0] if pi < len(pending) else -INF
            if a_time < not_before or a_time < best_src:
                break
            visit(p, sh, act, exits)
        start = max(sources, key=lambda s: latest.get(s, -INF))
        if latest.get(start, -INF) < not_before:
            return None
        return self._legs(start, jp)

    def _legs(self, start: int, jp: dict[int, tuple]) -> list[Leg] | None:
        legs: list[Leg] = []
        a = start
        t_walk = None
        for _ in range(30):
            step = jp.get(a)
            if step is None:
                return None
            if step[0] == "end":
                return legs
            if step[0] == "walk":
                b, s = step[1], step[2]
                t = t_walk if t_walk is not None else (legs[-1].arr if legs else 0)
                legs.append(Leg(a, b, t, t + s))
                a, t_walk = b, None
                continue
            _, i, e, sh = step
            legs.append(Leg(self.frm[i], self.to[e], self.dep[i] - sh, self.arr[e] - sh, self.trip[i]))
            a = self.to[e]
        return None

    def journey(self, sources: set[int], targets: set[int], day: dt.date, t: int,
                kinds: frozenset[int] | None = None) -> list[Leg] | None:
        """Schnellste Verbindung ab ``t`` – und davon die späteste Abfahrt (nicht unnötig früh losschicken)."""
        if not sources or not targets:
            return None
        if sources & targets:
            return []
        allowed = self.corridor(sources, targets)
        arrival = self.earliest_arrival(dict.fromkeys(sources, t), targets, day, allowed, kinds=kinds)
        if arrival is None:
            return None
        return _fix_walks(self.latest_journey(sources, targets, day, arrival, t, allowed, kinds))

    def last_journey(self, sources: set[int], targets: set[int], day: dt.date, t: int,
                     until: int = DAY + 3600, kinds: frozenset[int] | None = None) -> list[Leg] | None:
        """Letzte Verbindung des Tages (Ankunft spätestens ``until`` = 1 Uhr nachts, Abfahrt nicht vor ``t``).
        Nachtzüge um 3 Uhr früh sind für „der letzte Zug“ nicht gemeint."""
        if not sources or not targets or sources & targets:
            return None
        return _fix_walks(self.latest_journey(sources, targets, day, until, t, self.corridor(sources, targets),
                                              kinds))

    # ------------------------------------------------------------------ Beschreibung
    def trip_info(self, trip: int) -> tuple[int, str, str, str]:
        """(Art, Linie/Zugname, Ziel, Betreiber)."""
        kind, short, agency = self.routes[self.trip_route[trip]]
        name = self.strings[self.trip_name[trip]] or short
        return kind, name, self.strings[self.trip_head[trip]], agency

    def flex_at(self, area: int, day: dt.date) -> list[dict]:
        """Rufbus-Angebote (Zonen) an diesem Bereich, die an diesem Tag verkehren."""
        if not self.covers(day):
            return []
        off = (day - self.start).days
        return [self.flex[i] for i in self.area_flex.get(area, ())
                if self.services[self.flex[i]["service"] * self.ndays + off]]


def _fix_walks(legs: list[Leg] | None) -> list[Leg] | None:
    """Fußwege bekommen ihre Zeit vom Nachbarabschnitt (rückwärts gefundene Wege kennen sie nicht)."""
    if not legs:
        return legs
    out: list[Leg] = []
    for i, leg in enumerate(legs):
        if leg.trip >= 0:
            out.append(leg)
            continue
        dur = leg.arr - leg.dep
        if out:
            start = out[-1].arr
        else:
            nxt = next((x for x in legs[i + 1:] if x.trip >= 0), None)
            start = (nxt.dep - dur) if nxt else 0
        out.append(Leg(leg.frm, leg.to, start, start + dur))
    return out
