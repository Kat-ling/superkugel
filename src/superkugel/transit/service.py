"""Fahrplanauskunft: Paket laden (S3, einmal pro Container) und aus einer Frage eine gesprochene Antwort machen.

Alles deterministisch – die KI nennt nie selbst Zeiten. Ins Log kommen nur Art und Dauer der Auskunft, keine Orte.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from superkugel.config import Settings
from superkugel.language import MONTH_NAMES, WEEKDAY_NAMES, plain
from superkugel.services.logs import log
from superkugel.services.storage import Store
from superkugel.transit.ask import TransitQuery, parse
from superkugel.transit.build import KIND_BUS, KIND_CALL, KIND_OTHER, KIND_SUBWAY, KIND_TRAIN, KIND_TRAM
from superkugel.transit.places import CENTER_WORDS, Place, PlaceIndex, line_short, spoken_name, vehicle
from superkugel.transit.timetable import DAY, Leg, Timetable

POINTER = ("TRANSIT", "CURRENT")  # DynamoDB-Eintrag: welches Paket in S3 aktuell ist
NEXT_POINTER = ("TRANSIT", "NEXT")  # Paket, das erst ab seinem Startdatum gilt (Fahrplanwechsel im Dezember)
RECHECK_S = 600
RETURN_GAP_S = 600  # Rückfahrt frühestens 10 Minuten nach der Ankunft
TRAINS = frozenset({KIND_TRAIN})
BUSES = frozenset({KIND_BUS, KIND_CALL, KIND_TRAM, KIND_SUBWAY, KIND_OTHER})


@dataclass
class _Loaded:
    key: str = ""
    tt: Timetable | None = None
    places: PlaceIndex | None = None
    checked: float = 0.0


_CACHE = _Loaded()


def s3_reader(bucket: str, region: str) -> Callable[[str], bytes]:
    import boto3

    from superkugel.services.storage import fast_aws_config

    client = boto3.client("s3", region_name=region, config=fast_aws_config())
    return lambda key: client.get_object(Bucket=bucket, Key=key)["Body"].read()


def active_pointer(store: Store, today: dt.date) -> dict[str, Any]:
    """Das heute gültige Paket: das wartende, sobald sein Startdatum erreicht ist, sonst das aktuelle."""
    waiting = store.get_item(*NEXT_POINTER) or {}
    if waiting.get("key") and str(waiting.get("start", "")) <= today.isoformat():
        return waiting
    return store.get_item(*POINTER) or {}


@dataclass
class ImportPlan:
    """Was ein Fahrplan-Import tun soll (rein rechnerisch, damit es ohne AWS prüfbar ist)."""
    current: dict[str, Any] | None = None  # neuer Inhalt von POINTER, None = bleibt
    next: dict[str, Any] | None = None  # neuer Inhalt von NEXT_POINTER, None = bleibt
    clear_next: bool = False
    delete: list[str] = field(default_factory=list)  # alte Pakete in S3
    error: str = ""
    note: str = ""


def plan_import(current: dict[str, Any], waiting: dict[str, Any], new: dict[str, Any], today: dt.date) -> ImportPlan:
    """Ein Paket, das heute noch nicht gilt, wartet neben dem laufenden – sonst fehlten die Tage bis zum Wechsel."""
    if str(new["end"]) < today.isoformat():
        return ImportPlan(error=f"Dieser Fahrplan ist schon abgelaufen (gültig bis {new['end']}). Nichts geändert.")
    plan = ImportPlan()
    if waiting.get("key") and str(waiting.get("start", "")) <= today.isoformat():  # Wechsel ist schon passiert
        plan.current, plan.clear_next = dict(waiting), True
        plan.delete += [str(current["key"])] if current.get("key") else []
        current, waiting = dict(waiting), {}
    if str(new["start"]) <= today.isoformat():
        plan.current, plan.next, plan.clear_next = new, None, True
        plan.delete += [str(x["key"]) for x in (current, waiting) if x.get("key")]
        return plan
    plan.next, plan.clear_next = new, False
    plan.delete += [str(waiting["key"])] if waiting.get("key") else []
    end = str(current.get("end", ""))
    if end and (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat() < str(new["start"]):
        plan.note = f"Achtung: Lücke – der laufende Fahrplan endet {end}, der neue beginnt {new['start']}."
    return plan


def load(store: Store, settings: Settings, reader: Callable[[str], bytes] | None = None,
         clock: Callable[[], float] = time.monotonic, today: dt.date | None = None
         ) -> tuple[Timetable, PlaceIndex] | None:
    """Heute gültiges Paket (zwischengespeichert). None, wenn noch keines importiert wurde."""
    now = clock()
    if _CACHE.tt is not None and now - _CACHE.checked < RECHECK_S:
        return _CACHE.tt, _CACHE.places  # type: ignore[return-value]
    pointer = active_pointer(store, today or dt.date.today())
    key = str(pointer.get("key", ""))
    if not key:
        return None
    if key != _CACHE.key or _CACHE.tt is None:
        started = time.monotonic()
        read = reader or s3_reader(settings.audio_bucket, settings.aws_region)
        tt = Timetable(read(key))
        _CACHE.key, _CACHE.tt = key, tt
        _CACHE.places = PlaceIndex(tt, settings.transit_aliases, settings.home_stop or settings.home_station)
        log("transit_loaded", ms=int((time.monotonic() - started) * 1000))
    _CACHE.checked = now
    return _CACHE.tt, _CACHE.places  # type: ignore[return-value]


def reset_cache() -> None:
    global _CACHE
    _CACHE = _Loaded()


# ------------------------------------------------------------------ Sprechen
def clock_words(secs: int) -> str:
    secs %= DAY
    h, m = secs // 3600, secs % 3600 // 60
    return f"{h} Uhr {m}" if m else f"{h} Uhr"


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def day_words(day: dt.date, today: dt.date) -> str:
    if day == today:
        return "heute"
    if day == today + dt.timedelta(days=1):
        return "morgen"
    if day == today + dt.timedelta(days=2):
        return "übermorgen"
    return f"am {WEEKDAY_NAMES[day.weekday()]}, {day.day}. {MONTH_NAMES[day.month - 1]}"


def duration_words(secs: int) -> str:
    h, m = secs // 3600, round(secs % 3600 / 60)
    if h and m:
        return f"{h} {'Stunde' if h == 1 else 'Stunden'} {m} {'Minute' if m == 1 else 'Minuten'}"
    if h:
        return f"{h} {'Stunde' if h == 1 else 'Stunden'}"
    return f"{max(m, 1)} {'Minute' if m == 1 else 'Minuten'}"


def phone_words(phone: str) -> str:
    """„+43 4242 12345“ → in Zweiergruppen, damit Alexa es als Ziffern spricht."""
    digits = "".join(c for c in phone.replace("+43", "0") if c.isdigit())
    return " ".join(digits[i:i + 2] for i in range(0, len(digits), 2))


@dataclass
class Answer:
    text: str
    follow_up: dict[str, Any] | None = None  # für „und danach?“ / „genauer“
    kind: str = ""
    confirm: dict[str, Any] | None = None  # Rückfrage „Meinst du …?“: Frage, Rolle, Auswahl (Bereichs-IDs)


def answer(t: Callable[..., str], tt: Timetable, places: PlaceIndex, settings: Settings, text: str,
           now_local: dt.datetime, after: dict[str, Any] | None = None, detail: bool = False,
           chosen: dict[str, str] | None = None, back: bool = False) -> Answer:
    """Frage → Antwort. ``after``: letzte Auskunft, wenn sie „und danach?“ (oder mit ``detail`` „genauer“) fragt.
    ``back``: Rückfahrt zur letzten Auskunft (Sie selbst nennt höchstens Tag oder Zeit).
    ``chosen``: nach „Meinst du …?“ bestätigter Ort je Rolle (``origin``/``dest`` → Bereichs-ID)."""
    if back and after:
        q = _back_query(text, after, now_local)
    else:
        q = _query_from_follow_up(after, now_local) if after else parse(text, now_local)
    if q.vague and not after:  # „nächste Woche“: nachfragen statt für heute zu antworten
        return Answer(t("transit_ask_day"), {"text": text, "ask_day": True}, kind="ask_day")
    today = now_local.date()
    day = q.day or today
    t_now = now_local.hour * 3600 + now_local.minute * 60
    t0 = q.time_s if q.time_s is not None else (t_now if day == today else 5 * 3600)
    if back and after:
        if q.time_s is None and not q.day_said and after.get("arr_t") is not None:
            t0 = int(after["arr_t"]) + RETURN_GAP_S  # Hinfahrt bekannt: Rückfahrt nach der Ankunft
            if t0 >= DAY:
                day, t0 = day + dt.timedelta(days=1), t0 - DAY
    elif after:
        t0 = int(after.get("short_t") if detail and after.get("short_t") is not None else after.get("next_t") or t0)
    if not tt.covers(day):
        return Answer(t("transit_no_data_day", day=_capitalized(day_words(day, today))), kind="no_data")

    home_stop = places.by_gid(settings.home_stop) if settings.home_stop else None
    home_station = places.by_gid(settings.home_station) if settings.home_station else None
    rail = q.mode == "train"

    def resolve(said: str, role: str) -> Place | str | None:
        """Gesagter Name → Ort; ohne Namen „zu Hause“ (beim Zug der Heimatbahnhof). str = unbekannter Name."""
        if chosen and chosen.get(role) and (p := places.by_gid(chosen[role])):
            return p
        if said and home_station and plain(said) in ("bahnhof", "hauptbahnhof", "zug", "bahn"):
            return home_station  # „zum Bahnhof“ = der eigene
        if said and plain(said) in CENTER_WORDS:  # „in die Stadt“: Zentrum des Heimatorts, aus den Daten
            return places.center() or said
        if said:
            return places.find(said, rail=rail) or said
        return (home_station or home_stop) if rail else (home_stop or home_station)

    def ask_first(place: Place, role: str) -> Answer:
        """Gleichnamige Orte weit auseinander: erst nachfragen („Meinst du Sankt Johann in Tirol?“)."""
        gid = tt.areas[min(place.areas)].gid
        return Answer(t("transit_confirm", name=place.name), kind="confirm",
                      confirm={"text": text if not after else after.get("text", ""), "role": role,
                               "choices": [gid, *place.others], "chosen": dict(chosen or {})})

    origin = resolve(q.origin, "origin")
    if isinstance(origin, str):
        return Answer(t("transit_unknown_place", name=origin), kind="unknown")
    if origin is None:
        return Answer(t("transit_no_home"), kind="no_home")
    if origin.others:
        return ask_first(origin, "origin")
    dest: Place | str | None = None
    if q.dest or q.dest_home:
        dest = resolve(q.dest, "dest")
        if isinstance(dest, str):
            return Answer(t("transit_unknown_place", name=dest), kind="unknown")
        if dest is None:
            return Answer(t("transit_no_home"), kind="no_home")
        if dest.others:
            return ask_first(dest, "dest")

    if dest is None:
        return _departures(t, tt, q, origin, day, today, t0)
    if origin.areas & dest.areas:
        return Answer(t("transit_same_place", name=dest.name), kind="same")
    return _journey(t, tt, q, origin, dest, day, today, t0, short=not detail)


def _query_from_follow_up(after: dict[str, Any], now_local: dt.datetime) -> TransitQuery:
    q = parse(after.get("text", ""), now_local)
    q.day = dt.date.fromisoformat(after["day"]) if after.get("day") else q.day
    q.last = False
    return q


def _back_query(text: str, after: dict[str, Any], now_local: dt.datetime) -> TransitQuery:
    """„Und zurück?“: gesagte Zeit gilt, Orte kommen vertauscht aus der letzten Auskunft (``chosen``)."""
    q = parse(text, now_local)
    q.origin, q.dest, q.origin_home, q.dest_home = "", "", False, True
    if q.mode == "any":  # wie die Hinfahrt
        q.mode = {"zug": "train", "bus": "bus"}.get(str(after.get("text", "")).split(" ")[0], "any")
    if not q.day_said and after.get("day"):
        q.day = dt.date.fromisoformat(after["day"])
    return q


def _departures(t: Callable[..., str], tt: Timetable, q: TransitQuery, origin: Place, day: dt.date,
                today: dt.date, t0: int) -> Answer:
    kinds = TRAINS if q.mode == "train" else BUSES if q.mode == "bus" else None
    # „letzter Bus“: alle Abfahrten bis Betriebsschluss, davon die letzte
    limit, window = (10_000, max(0, DAY + 3600 - t0)) if q.last else (2, 6 * 3600)  # „letzter“: bis 1 Uhr nachts
    deps = tt.departures(set(origin.areas), day, t0, limit=limit, window_s=window, kinds=kinds)
    if not deps:  # hier selbst fährt nichts: Haltestellen in Gehweite (z. B. gegenüber)
        near = {b for x in origin.areas for b, _ in tt.foot.get(x, ())}
        deps = tt.departures(near, day, t0, limit=limit, window_s=window, kinds=kinds)
    when = day_words(day, today)
    if q.last and deps:
        d = deps[-1]
        _, _, head, _ = tt.trip_info(d.trip)
        return Answer(t("transit_departure_last", stop=spoken_name(tt.areas[d.area].name),
                        when="" if day == today else f"{when} ", time=clock_words(d.dep), line=line_short(tt, d.trip),
                        head=spoken_name(head)), kind="last_departure")
    parts: list[str] = []
    if not deps:
        parts.append(t("transit_no_departures", stop=origin.name, when=when))
    else:
        first = deps[0]
        _, _, head, _ = tt.trip_info(first.trip)
        prefix = "" if day == today else f"{when} "
        parts.append(t("transit_departure_first", stop=spoken_name(tt.areas[first.area].name), when=prefix,
                       time=clock_words(first.dep),
                       line=line_short(tt, first.trip), head=spoken_name(head)))
        for d in deps[1:]:
            _, _, head, _ = tt.trip_info(d.trip)
            parts.append(t("transit_departure_more", time=clock_words(d.dep), line=line_short(tt, d.trip),
                           head=spoken_name(head)))
    if q.mode != "train":
        for f in _flex(tt, origin, day)[:1]:
            parts.append(t("transit_flex", name=f["name"], start=clock_words(f["from"]), end=clock_words(f["to"]),
                           notice=f["notice_min"] or 30, phone=phone_words(f["phone"]) or "laut Aushang"))
    nxt = (deps[-1].dep + 60) if deps else None
    return Answer(" ".join(parts), {"text": q_text(q, origin, None), "day": day.isoformat(), "next_t": nxt,
                                    "places": _places_of(tt, origin, None)} if nxt else None, kind="departures")


def _flex(tt: Timetable, origin: Place, day: dt.date) -> list[dict]:
    seen, out = set(), []
    for a in origin.areas:
        for f in tt.flex_at(a, day):
            if f["name"] not in seen:
                seen.add(f["name"])
                out.append(f)
    return out


def q_text(q: TransitQuery, origin: Place, dest: Place | None) -> str:
    """Kurzform der Frage für „und danach?“ (bleibt nur in der Sitzung, nie im Log)."""
    mode = {"train": "zug", "bus": "bus"}.get(q.mode, "")
    return " ".join(x for x in (mode, f"von {origin.name}", f"nach {dest.name}" if dest else "") if x)


def _places_of(tt: Timetable, origin: Place, dest: Place | None) -> dict[str, str]:
    """Bereichs-IDs zur Kurzform – „danach“ findet so genau dieselben Orte wieder (ohne neue Rückfrage)."""
    out = {"origin": tt.areas[min(origin.areas)].gid}
    if dest:
        out["dest"] = tt.areas[min(dest.areas)].gid
    return out


def _journey(t: Callable[..., str], tt: Timetable, q: TransitQuery, origin: Place, dest: Place, day: dt.date,
             today: dt.date, t0: int, short: bool = True) -> Answer:
    src, dst = set(origin.areas), set(dest.areas)
    kinds = TRAINS if q.mode == "train" else None
    legs = None
    for k in ((kinds, None) if kinds else (None,)):
        legs = tt.last_journey(src, dst, day, t0, kinds=k) if q.last else tt.journey(src, dst, day, t0, kinds=k)
        if legs:
            break
    when = day_words(day, today)
    if not legs:
        return Answer(t("transit_no_connection", when=when, dest=dest.name), kind="none")
    rides = [x for x in legs if x.trip >= 0]
    day_prefix = "" if day == today else f"{when} "
    brief = short and len(rides) > 1  # mit Umstiegen erst die Kurzfassung, Einzelheiten auf „genauer“
    text = (_brief(t, tt, legs, dest, day_prefix, q.last) if brief
            else _describe(t, tt, legs, origin, dest, day_prefix, q.last))
    follow = {"text": q_text(q, origin, dest), "day": day.isoformat(), "next_t": legs[0].dep + 60 if not q.last
              else None, "short_t": legs[0].dep if brief else None, "arr_t": legs[-1].arr,
              "places": _places_of(tt, origin, dest)}
    return Answer(text, follow, kind=f"journey{len(rides)}")


def _changes(rides: int) -> str:
    return "ohne Umsteigen" if rides <= 1 else ("einmal umsteigen" if rides == 2 else f"{rides - 1} Mal umsteigen")


def _brief(t: Callable[..., str], tt: Timetable, legs: list[Leg], dest: Place, day_prefix: str, last: bool) -> str:
    """Kurzfassung: Abfahrt, wo umsteigen, Ankunft, Dauer – „genauer“ sagt alle Abschnitte."""
    rides = [x for x in legs if x.trip >= 0]
    first = rides[0]
    via = [spoken_name(tt.areas[x.to].name) for x in rides[:-1]]
    where = via[0] if len(via) == 1 else (" und ".join(via) if len(via) == 2 else via[0])
    changes = (f"einmal umsteigen in {where}" if len(via) == 1 else
               f"zweimal umsteigen, in {where}" if len(via) == 2 else f"{len(via)} Mal umsteigen, zuerst in {where}")
    parts = []
    if legs[0].trip < 0:
        parts.append(t("transit_walk_first", minutes=max(1, round((legs[0].arr - legs[0].dep) / 60)),
                       stop=spoken_name(tt.areas[legs[0].to].name)))
    parts.append(t("transit_brief_last" if last else "transit_brief", day=day_prefix, time=clock_words(first.dep),
                   stop=spoken_name(tt.areas[first.frm].name), vehicle=vehicle(tt, first.trip), changes=changes,
                   to=spoken_name(tt.areas[legs[-1].to].name), arr=clock_words(legs[-1].arr),
                   duration=duration_words(legs[-1].arr - legs[0].dep)))
    return " ".join(parts)


def _describe(t: Callable[..., str], tt: Timetable, legs: list[Leg], origin: Place, dest: Place, day_prefix: str,
              last: bool) -> str:
    parts: list[str] = []
    first_ride = True
    for i, leg in enumerate(legs):
        to_name = spoken_name(tt.areas[leg.to].name)
        if leg.trip < 0:
            parts.append(t("transit_walk", minutes=max(1, round((leg.arr - leg.dep) / 60)), stop=to_name))
            continue
        frm_name = spoken_name(tt.areas[leg.frm].name)
        key = "transit_leg_first" if first_ride else "transit_leg_next"
        if first_ride and last:
            key = "transit_leg_last"
        _, _, head, _ = tt.trip_info(leg.trip)
        parts.append(t(key, day=day_prefix, time=clock_words(leg.dep), stop=frm_name, vehicle=vehicle(tt, leg.trip),
                       head=spoken_name(head), to=to_name, arr=clock_words(leg.arr)))
        first_ride = False
        if i == len(legs) - 1:
            break
    rides = sum(1 for x in legs if x.trip >= 0)
    total = legs[-1].arr - legs[0].dep
    parts.append(t("transit_summary", duration=duration_words(total), changes=_changes(rides)))
    return " ".join(parts)


def _loaded(services: Any) -> tuple[Timetable, PlaceIndex] | None:
    from superkugel.services.usage import local_now

    try:
        return load(services.store, services.settings, services.transit_reader,
                    today=local_now(services.settings, services.now()).date())
    except Exception as exc:  # noqa: BLE001
        log("transit_load_failed", error=type(exc).__name__)
        return None


def knows_place(services: Any, said: str) -> bool:
    """Ist das eine bekannte Haltestelle (nur ganze Wörter)? Für Reisesätze ohne „Bus“/„Zug“ – sonst KI."""
    loaded = _loaded(services)
    if loaded is None:
        return False
    if plain(said) in CENTER_WORDS:
        return loaded[1].center() is not None
    return loaded[1].find(said, strict=True) is not None


def find_gid(services: Any, said: str) -> str:
    """Bereichs-ID eines gesagten Orts, nur wenn eindeutig (keine weitere Rückfrage nötig)."""
    loaded = _loaded(services)
    p = loaded[1].find(said) if loaded else None
    return loaded[0].areas[min(p.areas)].gid if loaded and p and not p.others else ""


def place_name(services: Any, gid: str) -> str:
    loaded = _loaded(services)
    p = loaded[1].by_gid(gid) if loaded else None
    return p.name if p else ""


def handle_text(services: Any, text: str, after: dict[str, Any] | None = None, detail: bool = False,
                chosen: dict[str, str] | None = None, back: bool = False) -> Answer:
    """Einstieg für Handler und KI-Werkzeug. Fehler → ehrlicher Satz, nie ein Absturz."""
    from superkugel.services.usage import local_now

    started = time.monotonic()
    loaded = _loaded(services)
    if loaded is None:
        return Answer(services.t("transit_unavailable"), kind="unavailable")
    tt, places = loaded
    if after and not chosen:
        chosen = after.get("places") or {}
        if back:
            chosen = {"origin": chosen.get("dest", ""), "dest": chosen.get("origin", "")}
    try:
        ans = answer(services.t, tt, places, services.settings, text, local_now(services.settings, services.now()),
                     after, detail=detail, chosen=chosen, back=back)
    except Exception as exc:  # noqa: BLE001
        log("transit_failed", error=type(exc).__name__)
        return Answer(services.t("transit_unavailable"), kind="error")
    log("transit_answer", kind=ans.kind, ms=int((time.monotonic() - started) * 1000))
    return ans
