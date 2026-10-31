"""GTFS-ZIPs → kompaktes Fahrplanpaket (läuft auf dem Admin-PC, nur Standardbibliothek).

Ergebnis ist ein ZIP mit Zahlenfeldern (``array``) statt einer Datenbank: Die Lambda lädt es einmal pro Container
in den Speicher und sucht dann in Millisekunden. Weggelassen werden Kartendaten (shapes.txt, Linienverläufe),
Wege in Bahnhöfen und alles, was für „Wann fährt …?“ nicht gebraucht wird.

Knoten der Verbindungssuche sind **Haltestellenbereiche** (österreichische Haltestellen-ID ohne Steig, z. B.
``at:99:1`` für alle Bahnsteige und Busbuchten eines Bahnhofs). Die IDs sind in allen Verbünden gleich – so
passen Bus (Kärntner Linien), Zug (ÖBB) und Tirol (VVT) ohne Zuordnungstabelle zusammen.
"""

from __future__ import annotations

import array
import csv
import datetime as dt
import io
import json
import math
import sys
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

FORMAT = 1
FOOTPATH_MAX_M = 400  # Umsteigen zu Fuß zwischen nahen Haltestellen (eigene Annahme, keine Angabe im GTFS)
WALK_BASE_S = 180  # Grundzeit je Fußweg (Orientieren, Treppen) – großzügig für ältere Fahrgäste
WALK_M_PER_S = 0.9  # langsam gerechnet
WALK_DETOUR = 1.3  # Luftlinie → Gehweg

# GTFS route_type (Basis + erweiterte Typen) → eigene Art
KIND_BUS, KIND_TRAIN, KIND_TRAM, KIND_SUBWAY, KIND_OTHER, KIND_CALL = 0, 1, 2, 3, 4, 5


def kind_of(route_type: str) -> int:
    try:
        t = int(route_type)
    except ValueError:
        return KIND_OTHER
    if t == 715:
        return KIND_CALL  # Anruf-Linienverkehr (Rufbus)
    if t == 2 or 100 <= t < 200:
        return KIND_TRAIN
    if t == 0 or 900 <= t < 1000:
        return KIND_TRAM
    if t == 1 or 400 <= t < 500:
        return KIND_SUBWAY
    if t == 3 or 700 <= t < 800 or t == 200:
        return KIND_BUS
    return KIND_OTHER


def area_of(stop_id: str, parent: str = "") -> str:
    """``at:99:1:0:7`` und ``Pat:99:1`` → ``at:99:1``; andere IDs bleiben (gekürzt auf 3 Teile)."""
    sid = parent or stop_id
    if sid.startswith("Pat:"):
        sid = sid[1:]
    parts = sid.split(":")
    return ":".join(parts[:3]) if len(parts) >= 3 else sid


def seconds(hms: str) -> int:
    h, m, s = (hms.strip() or "0:0:0").split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _rows(z: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    if name not in z.namelist():
        return
    with z.open(name) as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))
        reader.fieldnames = [h.strip() for h in reader.fieldnames or []]  # ein Feed hat „ location_id“
        yield from reader


def _date(s: str) -> dt.date:
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


@dataclass
class _Area:
    name: str
    lat: float = 0.0
    lon: float = 0.0
    n: int = 0
    weight: int = 0
    rail: bool = False


@dataclass
class BuildReport:
    feeds: list[str] = field(default_factory=list)
    trips: int = 0
    duplicate_trips: int = 0
    connections: int = 0
    areas: int = 0
    footpaths: int = 0
    flex_zones: int = 0
    flex_polygons_skipped: int = 0
    start: str = ""
    end: str = ""
    size_bytes: int = 0


def build(zips: Iterable[Path], out: Path) -> BuildReport:
    rep = BuildReport()
    zips = list(zips)
    if sys.byteorder != "little":
        raise RuntimeError("Nur für Little-Endian gebaut (wie AWS Lambda arm64/x86)")

    # ---------- 1. Kalender: Gültigkeitszeitraum aller Feeds
    starts, ends = [], []
    for p in zips:
        with zipfile.ZipFile(p) as z:
            for r in _rows(z, "calendar.txt"):
                starts.append(r["start_date"])
                ends.append(r["end_date"])
            for r in _rows(z, "calendar_dates.txt"):
                starts.append(r["date"])
                ends.append(r["date"])
    first, last = _date(min(starts)), _date(max(ends))
    ndays = (last - first).days + 1
    rep.start, rep.end = first.isoformat(), last.isoformat()

    areas: dict[str, _Area] = {}
    area_idx: dict[str, int] = {}
    area_list: list[_Area] = []  # gleiche Reihenfolge wie area_idx
    routes: list[tuple[int, str, str]] = []  # (art, Kurzname, Betreiber)
    strings: list[str] = [""]
    string_idx: dict[str, int] = {"": 0}
    services: list[bytearray] = []
    t_route, t_service, t_head, t_name = (array.array("i") for _ in range(4))
    seen_trips: set[tuple[str, str, str]] = set()
    conns: list[tuple[int, int, int, int, int, int]] = []  # dep, arr, frm, to, trip, flags
    flex: list[dict] = []

    def s_idx(s: str) -> int:
        s = s.strip()
        if s not in string_idx:
            string_idx[s] = len(strings)
            strings.append(s)
        return string_idx[s]

    def a_idx(key: str, name: str) -> int:
        if key not in area_idx:
            area_idx[key] = len(area_idx)
            areas[key] = _Area(name=name)
            area_list.append(areas[key])
        return area_idx[key]

    for p in zips:
        feed = p.stem
        rep.feeds.append(feed)
        with zipfile.ZipFile(p) as z:
            agencies = {r["agency_id"]: r["agency_name"] for r in _rows(z, "agency.txt")}
            stop_area: dict[str, str] = {}
            for r in _rows(z, "stops.txt"):
                key = area_of(r["stop_id"], r.get("parent_station", "").strip())
                stop_area[r["stop_id"]] = key
                if r.get("location_type", "") in ("", "0", "1"):
                    a_idx(key, r["stop_name"].strip())
                    a = areas[key]
                    try:
                        lat, lon = float(r["stop_lat"]), float(r["stop_lon"])
                    except ValueError:
                        continue
                    a.lat, a.lon, a.n = (a.lat * a.n + lat) / (a.n + 1), (a.lon * a.n + lon) / (a.n + 1), a.n + 1
                    if r.get("location_type") == "1":
                        a.name = r["stop_name"].strip()  # Name der Station hat Vorrang

            route_map: dict[str, int] = {}
            for r in _rows(z, "routes.txt"):
                route_map[r["route_id"]] = len(routes)
                routes.append((kind_of(r["route_type"]), (r.get("route_short_name") or "").strip(),
                               agencies.get(r.get("agency_id", ""), "")))

            svc_map: dict[str, int] = {}

            def svc(sid: str, svc_map: dict[str, int] = svc_map) -> int:
                if sid not in svc_map:
                    svc_map[sid] = len(services)
                    services.append(bytearray(ndays))
                return svc_map[sid]

            for r in _rows(z, "calendar.txt"):
                bits = services[svc(r["service_id"])]
                days = [r[d] == "1" for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
                                              "sunday")]
                d, end = _date(r["start_date"]), _date(r["end_date"])
                while d <= end:
                    if days[d.weekday()]:
                        bits[(d - first).days] = 1
                    d += dt.timedelta(days=1)
            for r in _rows(z, "calendar_dates.txt"):
                bits = services[svc(r["service_id"])]
                bits[(_date(r["date"]) - first).days] = 1 if r["exception_type"] == "1" else 0

            trip_map: dict[str, int] = {}
            for r in _rows(z, "trips.txt"):
                sig = (r["trip_id"], r["service_id"], r["route_id"])
                if sig in seen_trips:  # Kärntner Linien „flex“ enthält den normalen Fahrplan noch einmal
                    rep.duplicate_trips += 1
                    continue
                seen_trips.add(sig)
                trip_map[r["trip_id"]] = len(t_route)
                t_route.append(route_map[r["route_id"]])
                t_service.append(svc(r["service_id"]))
                t_head.append(s_idx(r.get("trip_headsign", "")))
                t_name.append(s_idx(r.get("trip_short_name", "")))

            booking = {r["booking_rule_id"]: r for r in _rows(z, "booking_rules.txt")}
            group_name = {r["location_group_id"]: r["location_group_name"] for r in _rows(z, "location_groups.txt")}
            group_areas: dict[str, set[str]] = defaultdict(set)
            for r in _rows(z, "location_group_stops.txt"):
                group_areas[r["location_group_id"]].add(stop_area.get(r["stop_id"], area_of(r["stop_id"])))

            # stop_times: nach Fahrt gruppieren (Dateien sind nach trip_id sortiert, sicherheitshalber sammeln)
            by_trip: dict[int, list[tuple[int, int, int, int, int]]] = defaultdict(list)
            flex_seen: set[tuple] = set()
            for r in _rows(z, "stop_times.txt"):
                ti = trip_map.get(r["trip_id"])
                if ti is None:
                    continue
                sid = (r.get("stop_id") or "").strip()
                if not sid:
                    gid = (r.get("location_group_id") or "").strip()
                    if not gid:
                        rep.flex_polygons_skipped += 1  # Rufgebiete als Fläche (GeoJSON) – nicht unterstützt
                        continue
                    rule = booking.get((r.get("pickup_booking_rule_id") or "").strip(), {})
                    key = (gid, t_service[ti], r.get("start_pickup_drop_off_window"), r.get("end_pickup_drop_off_window"))
                    if key in flex_seen:
                        continue
                    flex_seen.add(key)
                    flex.append({
                        "name": group_name.get(gid, "") or routes[t_route[ti]][1],
                        "service": t_service[ti],
                        "from": seconds(r.get("start_pickup_drop_off_window") or "0:0:0"),
                        "to": seconds(r.get("end_pickup_drop_off_window") or "24:0:0"),
                        "phone": (rule.get("phone_number") or "").strip(),
                        "notice_min": int(rule.get("prior_notice_duration_min") or 0),
                        "url": (rule.get("booking_url") or "").strip(),
                        "areas": sorted(group_areas.get(gid, set())),
                    })
                    continue
                key = stop_area.get(sid, area_of(sid))
                a = a_idx(key, key)
                arr = seconds(r.get("arrival_time") or r.get("departure_time") or "")
                dep = seconds(r.get("departure_time") or r.get("arrival_time") or "")
                pick = 1 if (r.get("pickup_type") or "").strip() == "1" else 0
                drop = 1 if (r.get("drop_off_type") or "").strip() == "1" else 0
                by_trip[ti].append((int(r["stop_sequence"]), a, arr, dep, pick | (drop << 1)))

            for ti, sts in by_trip.items():
                sts.sort()
                kind = routes[t_route[ti]][0]
                prev = None
                for st in sts:
                    if prev is not None and st[1] != prev[1]:
                        flags = (prev[4] & 1) | (st[4] & 2)
                        conns.append((prev[3], st[2], prev[1], st[1], ti, flags))
                    # zwei Steige desselben Bereichs hintereinander: zusammenfassen
                    same = prev is not None and st[1] == prev[1]
                    prev = (prev[0], prev[1], prev[2], st[3], prev[4] & st[4]) if same else st
                for _, a, _arr, _dep, _ in sts:
                    ar = area_list[a]
                    ar.weight += 1
                    if kind == KIND_TRAIN:
                        ar.rail = True
        rep.trips = len(t_route)

    # ---------- Alle Bereiche behalten: auch ohne eigene Abfahrt sind sie Start (Fußweg, Rufbus-Zone)
    used = list(range(len(area_idx)))
    keys = list(area_idx)
    renum = {old: new for new, old in enumerate(used)}
    out_areas = [keys[i] for i in used]
    conns = [(d, a, renum[f], renum[t], tr, fl) for d, a, f, t, tr, fl in conns]
    conns.sort()
    rep.connections, rep.areas = len(conns), len(out_areas)

    # ---------- Fußwege zwischen nahen Bereichen (Raster ≈ 0,005°)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    coords = [(areas[k].lat, areas[k].lon) for k in out_areas]
    for i, (lat, lon) in enumerate(coords):
        if lat or lon:
            grid[(int(lat / 0.005), int(lon / 0.005))].append(i)
    foot: list[tuple[int, int, int]] = []
    for i, (lat, lon) in enumerate(coords):
        if not (lat or lon):
            continue
        gx, gy = int(lat / 0.005), int(lon / 0.005)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    if j != i:
                        d = _meters(lat, lon, *coords[j])
                        if d <= FOOTPATH_MAX_M:
                            foot.append((i, j, int(WALK_BASE_S + d * WALK_DETOUR / WALK_M_PER_S)))
    rep.footpaths = len(foot)

    flex_out = []
    for f in flex:
        ids = [renum[area_idx[k]] for k in f["areas"] if k in area_idx and area_idx[k] in renum]
        if ids:
            flex_out.append({**f, "areas": ids})
    rep.flex_zones = len(flex_out)

    def arr_bytes(values: Iterable[int], code: str = "i") -> bytes:
        return array.array(code, values).tobytes()

    meta = {"format": FORMAT, "built": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "start": rep.start,
            "end": rep.end, "days": ndays, "feeds": rep.feeds}
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("meta.json", json.dumps(meta))
        z.writestr("areas.json", json.dumps([[k, areas[k].name, round(areas[k].lat, 6), round(areas[k].lon, 6),
                                              areas[k].weight, int(areas[k].rail)] for k in out_areas],
                                            ensure_ascii=False))
        z.writestr("routes.json", json.dumps(routes, ensure_ascii=False))
        z.writestr("strings.json", json.dumps(strings, ensure_ascii=False))
        z.writestr("flex.json", json.dumps(flex_out, ensure_ascii=False))
        z.writestr("services.bin", b"".join(bytes(b) for b in services))
        for name, arr_ in (("trip_route", t_route), ("trip_service", t_service), ("trip_head", t_head),
                           ("trip_name", t_name)):
            z.writestr(f"{name}.bin", arr_.tobytes())
        for i, name in enumerate(("dep", "arr", "frm", "to", "trip")):
            z.writestr(f"conn_{name}.bin", arr_bytes(c[i] for c in conns))
        z.writestr("conn_flags.bin", bytes(c[5] for c in conns))
        # Reihenfolge nach Ankunft – für die Rückwärtssuche („spätestens losfahren“), in der Lambda zu teuer
        by_arr = sorted(range(len(conns)), key=lambda i: (conns[i][1], conns[i][0]))
        z.writestr("conn_by_arr.bin", arr_bytes(by_arr))
        z.writestr("conn_arr_sorted.bin", arr_bytes(conns[i][1] for i in by_arr))
        for i, name in enumerate(("a", "b", "s")):
            z.writestr(f"foot_{name}.bin", arr_bytes(f[i] for f in foot))
    rep.size_bytes = out.stat().st_size
    return rep


def _meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat2 - lat1) * 111_320, (lon2 - lon1) * 111_320 * k)
