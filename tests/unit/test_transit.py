"""Fahrplan (v1.4): Paket bauen, Verbindungssuche, Satzverständnis, Haltestellensuche, Ansagen – ohne Netz."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from superkugel.config import Settings, _aliases, _stop_id
from superkugel.speech.texts import text as T
from superkugel.transit.ask import looks_like_transit, parse, travel_dest
from superkugel.transit.build import build
from superkugel.transit.places import PlaceIndex, spoken_name
from superkugel.transit.service import answer, clock_words, phone_words, plan_import
from superkugel.transit.timetable import Timetable
from superkugel.transit.trip import Change
from transit_fixture import package, write_feeds

VIE = ZoneInfo("Europe/Vienna")
TUE = dt.date(2026, 11, 3)


@pytest.fixture(scope="module")
def tt(tmp_path_factory) -> Timetable:
    return Timetable(package(tmp_path_factory.mktemp("fp")))


def a(tt: Timetable, gid: str) -> int:
    return tt.by_gid[gid]


def hm(s: int) -> str:
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}"


def test_build_dedupes_skips_maps_and_keeps_flex(tmp_path) -> None:
    rep = build(write_feeds(tmp_path / "g"), tmp_path / "p.zip")
    assert rep.duplicate_trips == 1  # t_bus_1000 steht in beiden Feeds
    assert rep.flex_zones == 1 and rep.flex_polygons_skipped == 1
    assert (rep.start, rep.end) == ("2026-11-01", "2026-12-12")
    assert rep.areas == 8 and rep.footpaths >= 2  # Bahnsteige zu einem Bereich zusammengefasst, Nord ohne Abfahrt bleibt


def test_journey_with_change_and_latest_departure(tt: Timetable) -> None:
    legs = tt.journey({a(tt, "at:99:2")}, {a(tt, "at:99:3")}, TUE, 8 * 3600 + 10 * 60)
    rides = [(hm(x.dep), tt.areas[x.frm].name, hm(x.arr), tt.areas[x.to].name) for x in legs]
    # nicht der 8:20-Bus (40 min warten), sondern der 8:50-Bus – gleiche Ankunft
    assert rides == [("08:50", "Teststadt Marktplatz", "09:00", "Teststadt Hbf"),
                     ("09:10", "Teststadt Hbf", "09:50", "Bergdorf Bahnhof")]


def test_three_legs_footpath_and_no_pickup_flags(tt: Timetable) -> None:
    legs = tt.journey({a(tt, "at:99:5")}, {a(tt, "at:99:4")}, TUE, 8 * 3600 + 30 * 60)
    kinds = ["walk" if x.trip < 0 else tt.trip_info(x.trip)[1] for x in legs]
    assert kinds[0] == "walk" and kinds[-1] == "8" and "REX 1234" in kinds
    assert hm(legs[-1].arr) == "10:20"
    # Aussteigen am Start der Fahrt ist verboten (drop_off_type=1) → kein „Rückweg“ über den Startpunkt
    assert tt.journey({a(tt, "at:99:3")}, {a(tt, "at:99:1")}, TUE, 17 * 3600) is None


def test_calendar_exceptions_sunday_and_overnight(tt: Timetable) -> None:
    hbf, berg = {a(tt, "at:99:1")}, {a(tt, "at:99:3")}
    assert tt.journey(hbf, berg, dt.date(2026, 11, 4), 9 * 3600) is None  # Feiertag: kein Werktagsverkehr
    sun = tt.journey(hbf, berg, dt.date(2026, 11, 8), 9 * 3600)
    assert hm(sun[0].dep) == "10:10"
    night = tt.journey(hbf, berg, TUE, 23 * 3600 + 40 * 60)
    assert hm(night[0].dep) == "23:50" and night[0].arr == 24 * 3600 + 30 * 60
    assert clock_words(night[0].arr) == "0 Uhr 30"
    assert not tt.covers(dt.date(2026, 12, 13))


def test_departures_last_and_flex(tt: Timetable) -> None:
    deps = tt.departures({a(tt, "at:99:2")}, TUE, 8 * 3600)
    assert [hm(d.dep) for d in deps] == ["08:20", "08:50"]
    last = tt.last_journey({a(tt, "at:99:1")}, {a(tt, "at:99:3")}, TUE, 8 * 3600)
    assert hm(last[0].dep) == "23:50"
    flex = tt.flex_at(a(tt, "at:99:2"), TUE)
    assert flex[0]["name"] == "Testrufbus" and flex[0]["notice_min"] == 60
    assert tt.flex_at(a(tt, "at:99:2"), dt.date(2026, 11, 7)) == []  # Samstag kein Rufbus


@pytest.mark.parametrize(("said", "expect"), [
    ("wann fährt der nächste Zug nach Bergdorf", ("train", "", "bergdorf", False)),
    ("wie komm ich morgen um halb neun nach Seeort", ("any", "", "seeort", False)),
    ("wann geht der letzte Bus von Teststadt heim", ("bus", "teststadt", "", True)),
    ("fährt heute noch ein Zug von Teststadt Hbf nach Bergdorf", ("train", "teststadt hbf", "bergdorf", False)),
    ("nächster Bus", ("bus", "", "", False)),
])
def test_parse_sentences(said: str, expect: tuple) -> None:
    q = parse(said, dt.datetime(2026, 11, 3, 8, 0, tzinfo=VIE))
    assert (q.mode, q.origin, q.dest, q.last) == expect


def test_parse_times() -> None:
    now = dt.datetime(2026, 11, 3, 10, 0, tzinfo=VIE)  # Dienstag
    assert (parse("morgen um halb neun nach x", now).time_s, parse("morgen um halb neun nach x", now).day) == (
        8 * 3600 + 30 * 60, dt.date(2026, 11, 4))
    assert parse("um drei nach x", now).time_s == 15 * 3600  # nachmittags gemeint
    assert parse("am samstag in der früh nach x", now).day == dt.date(2026, 11, 7)
    assert parse("um acht nach x", now).day == dt.date(2026, 11, 4)  # 8 Uhr heute vorbei → morgen
    assert parse("um viertel nach sieben am abend nach x", now).time_s == 19 * 3600 + 15 * 60
    assert parse("nach x ab acht", now).dest == "x"


def test_looks_like_transit() -> None:
    assert looks_like_transit("wann fährt der nächste Bus")
    assert looks_like_transit("wie komm ich nach Bergdorf")
    assert not looks_like_transit("wie komm ich auf andere Gedanken")
    assert not looks_like_transit("was koch ich heute")


def test_places_town_rail_near_fuzzy_alias(tt: Timetable) -> None:
    pl = PlaceIndex(tt, {"oma": "at:99:4"}, home_gid="at:99:5")
    assert pl.find("Teststadt").name == "Teststadt Hauptbahnhof"  # Ort → Bahnhof
    assert pl.find("Marktplatz").areas == frozenset({a(tt, "at:99:2")})  # ohne Ort → der nächste
    assert pl.find("Bergdorff").name == "Bergdorf Bahnhof"  # Erkennungsfehler
    assert pl.find("oma").name == "Seeort Kirche"
    assert pl.find("Mondstadt") is None
    assert spoken_name("St.Johann i. T. Bf (B83)") == "Sankt Johann in Tirol Bahnhof"
    assert spoken_name("Feldkirchen in Ktn Bf") == "Feldkirchen in Kärnten Bahnhof"
    assert spoken_name("Heiligengeist b.Bergdorf Ort") == "Heiligengeist bei Bergdorf Ort"


def _ans(tt: Timetable, text: str, now: dt.datetime, form: str = "du", **kw) -> str:
    s = Settings(home_stop="at:99:5", home_station="at:99:1", address_form=form, **kw)
    pl = PlaceIndex(tt, s.transit_aliases, s.home_stop)
    return answer(lambda k, **x: T(form, k, **x), tt, pl, s, text, now).text


def test_answers_spoken(tt: Timetable) -> None:
    now = dt.datetime(2026, 11, 3, 8, 10, tzinfo=VIE)
    s = _ans(tt, "wann fährt der nächste Zug nach Bergdorf", now)
    assert s.startswith("Laut Fahrplan: um 9 Uhr 10 ab Teststadt Hauptbahnhof mit dem Regionalexpress")
    assert "an Bergdorf Bahnhof um 9 Uhr 50" in s and "ohne Umsteigen" in s
    s = _ans(tt, "wie komm ich nach Seeort", now)
    assert s.startswith("Erst etwa 8 Minuten zu Fuß zur Haltestelle Teststadt Marktplatz. Laut Fahrplan: um 8 Uhr 50")
    assert "zweimal umsteigen, in Teststadt Hauptbahnhof und Bergdorf Bahnhof" in s and "„genauer“" in s
    assert "Bus 8" not in s  # Kurzfassung: Einzelheiten erst auf „genauer“
    s = _ans(tt, "nächster Bus", now)
    assert "Linie 7" in s and "Rufbus Testrufbus" in s and "60 Minuten" in s and "01 23 45 67 8" in s
    assert "Den müssen Sie" in _ans(tt, "nächster Bus", now, form="sie")
    assert "keinen Fahrplan" in _ans(tt, "wann fährt am 20. Dezember ein Zug nach Bergdorf übermorgen",
                                      dt.datetime(2026, 12, 11, 9, tzinfo=VIE))
    assert "kenne ich leider nicht" in _ans(tt, "wie komm ich nach Mondstadt", now)
    assert "Die letzte Verbindung" in _ans(tt, "wann geht der letzte Zug nach Bergdorf", now)


def test_helpers() -> None:
    assert phone_words("+43 4242 12345") == "04 24 21 23 45"
    assert _stop_id("at:42:4711:0:3") == "at:42:4711" and _stop_id("x") == ""
    assert _aliases("Bergdorf=at:47:9999:0:1;kaputt=;=at:1:2") == {"bergdorf": "at:47:9999"}


# ------------------------------------------------------------------ v1.5: Orte tolerant, Reisesätze, Kurzfassung
def test_places_hints_short_names_synonyms_center(tt: Timetable) -> None:
    pl = PlaceIndex(tt, {}, home_gid="at:99:5")
    first = pl.find("Lindenau")  # zweimal vorhanden, keiner in der Nähe → mit Rückfrage
    assert first.name == "Lindenau Bahnhof" and first.others == ("at:99:7",)
    near = pl.find("Lindenau bei Bergdorf")  # Zusatz wählt aus, keine Rückfrage
    assert near.name == "Lindenau Bahnhof" and near.others == ()
    assert pl.find("Lindenau in Niederösterreich").name == "Lindenau Kirche"
    assert pl.find("Lindenau bei Mondstadt").others  # unbekannter Zusatz → wie ohne Zusatz
    assert pl.find("Bergdorf zu meiner Schwester").name == "Bergdorf Bahnhof"  # Kurzname mitten im Satz
    assert pl.find("Krankenhaus").name == "Teststadt LKH Eingang"
    assert pl.center().name == "Teststadt Marktplatz"  # meiste Abfahrten im Heimatort, aus den Daten
    assert pl.find("Bergdor", strict=True) is None and pl.find("Bergdorff", strict=True) is None
    assert pl.find("Bergdorf", strict=True).name == "Bergdorf Bahnhof"


@pytest.mark.parametrize(("said", "dest"), [
    ("ich möchte morgen nach Bergdorf fahren", "bergdorf"),
    ("zu meiner Tochter nach Lindenau bei Bergdorf", "lindenau bei bergdorf"),
    ("ich möchte in die Stadt fahren", "stadtzentrum"),
    ("ich möchte morgen in die Stadt nach Bergdorf", "bergdorf"),
    ("ich muss nach dem Essen schlafen", ""),
    ("ich will nach Hause", ""),
    ("ich möchte nach acht schlafen", ""),
    ("was koch ich heute", ""),
    ("und will nach Bergdorf", "bergdorf"),
    ("morgen muss ich nach Bergdorf", "bergdorf"),
    ("meine Tochter und ich wollen nach Bergdorf", "bergdorf"),
    ("ich will heute nicht in die Stadt fahren", ""),
    ("ich möchte nicht nach Bergdorf fahren", ""),
    ("meine Tochter muss morgen in die Stadt", ""),
    ("mein Sohn will nach Bergdorf ziehen", ""),
    ("ich geh zu Fuß in die Stadt", ""),
    ("ich möchte mit dem Auto nach Bergdorf", ""),
    ("wenn ich nach Bergdorf fahre", ""),
    ("ich will nach Bergdorf ziehen", ""),
])
def test_travel_dest(said: str, dest: str) -> None:
    assert travel_dest(said) == dest


def test_brief_then_detail_and_confirm(tt: Timetable) -> None:
    now = dt.datetime(2026, 11, 3, 8, 10, tzinfo=VIE)
    s = Settings(home_stop="at:99:5", home_station="at:99:1", address_form="du")
    pl = PlaceIndex(tt, {}, s.home_stop)

    def ask(text: str, **kw):
        return answer(lambda k, **x: T("du", k, **x), tt, pl, s, text, now, **kw)

    brief = ask("wie komm ich nach Seeort")
    full = ask("", trip=brief.trip, change=Change("genauer"))
    assert "mit dem Bus 8" in full.text and "2 Mal umsteigen" in full.text and "8 Uhr 50" in full.text
    q = ask("wann fährt ein Zug nach Lindenau")
    assert q.kind == "confirm" and q.text == "Meinst du Lindenau Bahnhof?"
    assert q.confirm["choices"] == ["at:99:6", "at:99:7"] and q.confirm["role"] == "dest"
    ok = ask(q.confirm["text"], chosen={"dest": "at:99:6"})
    assert "Lindenau Bahnhof" in ok.text and ok.kind.startswith("journey")
    assert "Teststadt Marktplatz" in ask("ich möchte in die Stadt fahren").text  # Zentrum aus den Daten


@pytest.mark.parametrize(("said", "day", "secs"), [
    ("am 20. november nach x", dt.date(2026, 11, 20), None),
    ("am zwanzigsten november nach x", dt.date(2026, 11, 20), None),
    ("am 20.11. nach x", dt.date(2026, 11, 20), None),
    ("am 20.11.2026 um 14 uhr nach x", dt.date(2026, 11, 20), 14 * 3600),
    ("am 20. nach x", dt.date(2026, 11, 20), None),
    ("am 2. nach x", dt.date(2026, 12, 2), None),  # schon vorbei → nächster Monat
    ("am dritten jänner nach x", dt.date(2027, 1, 3), None),
    ("in zwei stunden nach x", TUE, 12 * 3600),
    ("in einer stunde nach x", TUE, 11 * 3600),
    ("in einer halben stunde nach x", TUE, 10 * 3600 + 1800),
    ("in eineinhalb stunden nach x", TUE, 11 * 3600 + 1800),
    ("in zehn minuten nach x", TUE, 10 * 3600 + 600),
    ("in 15 stunden nach x", dt.date(2026, 11, 4), 3600),
    ("in drei tagen nach x", dt.date(2026, 11, 6), None),
    ("in einer woche um 8 uhr nach x", dt.date(2026, 11, 10), 8 * 3600),
    ("nächsten dienstag nach x", dt.date(2026, 11, 10), None),
    ("nächste woche am donnerstag nach x", dt.date(2026, 11, 12), None),
    ("heute abend nach x", TUE, 17 * 3600),
    ("am abend nach x", TUE, 17 * 3600),
    ("am morgen nach x", dt.date(2026, 11, 4), 6 * 3600),  # heute früh ist vorbei
])
def test_dates_and_relative_times(said: str, day: dt.date, secs: int | None) -> None:
    q = parse(said, dt.datetime(2026, 11, 3, 10, 0, tzinfo=VIE))
    assert (q.day, q.time_s, q.dest, q.vague) == (day, secs, "x", False)


@pytest.mark.parametrize("said", ["nächste woche nach x", "am wochenende nach x", "zu weihnachten nach x"])
def test_vague_days(said: str) -> None:
    q = parse(said, dt.datetime(2026, 11, 3, 10, 0, tzinfo=VIE))
    assert q.vague and q.dest == "x"


def test_impossible_date_is_vague_not_today() -> None:
    assert parse("am 31. november nach x", dt.datetime(2026, 11, 3, 10, 0, tzinfo=VIE)).vague


def test_time_like_words_are_no_places() -> None:
    now = dt.datetime(2026, 11, 3, 10, 0, tzinfo=VIE)
    assert parse("ab dem 20. november nach x", now).origin == ""
    assert parse("nach x in zwei stunden", now).dest == "x"
    assert parse("nach Sankt Johann in Tirol", now).dest == "sankt johann in tirol"


def _plan(cur: dict, nxt: dict, start: str, end: str = "2027-12-11"):
    return plan_import(cur, nxt, {"key": "neu", "start": start, "end": end}, dt.date(2026, 11, 30))


OLD = {"key": "alt", "start": "2025-12-14", "end": "2026-12-12"}


def test_import_future_timetable_waits_and_keeps_the_current_one() -> None:
    p = _plan(OLD, {}, "2026-12-13")
    assert p.current is None and p.next["key"] == "neu" and p.delete == [] and not p.error and not p.note


def test_import_valid_today_replaces_and_cleans_up() -> None:
    p = _plan(OLD, {"key": "wartend", "start": "2026-12-13"}, "2026-11-30")
    assert p.current["key"] == "neu" and p.next is None and p.clear_next and p.delete == ["alt", "wartend"]


def test_import_replaces_a_waiting_timetable_only() -> None:
    p = _plan(OLD, {"key": "wartend", "start": "2026-12-13"}, "2026-12-13")
    assert p.current is None and p.next["key"] == "neu" and p.delete == ["wartend"]


def test_import_promotes_a_timetable_already_in_use() -> None:
    p = _plan(OLD, {"key": "aktiv", "start": "2026-11-29"}, "2027-12-12")
    assert p.current["key"] == "aktiv" and p.next["key"] == "neu" and p.delete == ["alt"]


def test_import_refuses_expired_and_warns_about_gaps() -> None:
    assert _plan(OLD, {}, "2025-01-01", "2026-11-29").error
    assert "Lücke" in _plan(OLD, {}, "2026-12-20").note
