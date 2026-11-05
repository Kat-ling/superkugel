"""Reise-Stand: Jede Nachfrage ändert nur, was sie nennt (erfundene Orte, ohne KI und ohne Fahrplan)."""

from __future__ import annotations

import datetime as dt

from superkugel.transit.trip import Change, Spot, Trip, merge, trip_text

TODAY = dt.date(2026, 11, 3)


def trip(**kw) -> Trip:
    base = {"origin": Spot("at:1", "Teststadt", home=True), "dest": Spot("at:2", "Bergdorf"), "day": "2026-11-05",
            "time_s": 5 * 3600, "mode": "train", "dep": 9 * 3600, "arr": 10 * 3600}
    return Trip(**{**base, **kw})


def test_time_only_keeps_day_places_and_vehicle() -> None:
    m = merge(trip(), Change("aendern", zeit_s=10 * 3600), TODAY)
    assert (m.day, m.time_s, m.mode, m.origin.gid, m.dest.gid) == ("2026-11-05", 10 * 3600, "train", "at:1", "at:2")


def test_empty_fields_change_nothing_but_forget_the_shown_ride() -> None:
    m = merge(trip(short=True), Change("aendern"), TODAY)
    assert (m.day, m.time_s, m.mode) == ("2026-11-05", 5 * 3600, "train")
    assert (m.dep, m.arr, m.short) == (None, None, False)


def test_new_day_keeps_the_time() -> None:
    m = merge(trip(), Change("aendern", tag="2026-11-06"), TODAY)
    assert (m.day, m.time_s) == ("2026-11-06", 5 * 3600)


def test_day_out_of_range_is_left_open() -> None:
    assert merge(trip(), Change("aendern", tag="2026-11-02"), TODAY).open == "day"
    assert merge(trip(), Change("aendern", tag="2027-12-01"), TODAY).open == "day"
    assert merge(trip(), Change("aendern", tag="unsinn"), TODAY).open == "day"
    assert merge(trip(), Change("aendern", tag="2027-11-08"), TODAY).open == ""


def test_new_destination_and_start_are_names_until_resolved() -> None:
    m = merge(trip(), Change("aendern", ziel="Seeort", naehe="Bergdorf"), TODAY)
    assert (m.dest.gid, m.dest.name, m.origin.gid) == ("", "Seeort bei Bergdorf", "at:1")
    m = merge(trip(), Change("aendern", start="Seeort"), TODAY)
    assert (m.origin.gid, m.origin.name, m.origin.home, m.dest.gid) == ("", "Seeort", False, "at:2")


def test_vehicle_and_last_can_change() -> None:
    m = merge(trip(), Change("aendern", mode="bus", last=True), TODAY)
    assert (m.mode, m.last) == ("bus", True)
    assert merge(trip(last=True), Change("aendern", zeit_s=3600), TODAY).last is False  # Uhrzeit schlägt „letzte“


def test_return_starts_after_the_arrival_with_offset() -> None:
    m = merge(trip(), Change("rueckfahrt", bezug="nach_ankunft", versatz_min=60), TODAY)
    assert (m.origin.gid, m.dest.gid, m.origin.home, m.dest.home) == ("at:2", "at:1", False, True)
    assert (m.day, m.time_s, m.dep, m.arr) == ("2026-11-05", 11 * 3600, None, None)


def test_return_after_departure_and_past_midnight() -> None:
    assert merge(trip(), Change("rueckfahrt", bezug="nach_abfahrt", versatz_min=30), TODAY).time_s == 9 * 3600 + 1800
    m = merge(trip(arr=23 * 3600 + 3000), Change("rueckfahrt", bezug="nach_ankunft", versatz_min=30), TODAY)
    assert (m.day, m.time_s) == ("2026-11-06", 1200)


def test_return_at_a_said_time_or_day() -> None:
    assert merge(trip(), Change("rueckfahrt", zeit_s=16 * 3600), TODAY).time_s == 16 * 3600
    m = merge(trip(), Change("rueckfahrt", tag="2026-11-07"), TODAY)
    assert (m.day, m.time_s) == ("2026-11-07", None)


def test_return_without_a_known_arrival_uses_the_kept_day() -> None:
    m = merge(trip(dep=None, arr=None), Change("rueckfahrt", bezug="nach_ankunft", versatz_min=10), TODAY)
    assert (m.day, m.time_s, m.origin.gid) == ("2026-11-05", None, "at:2")


def test_return_needs_a_destination() -> None:
    assert merge(trip(dest=None), Change("rueckfahrt"), TODAY).open == "dest"


def test_return_keeps_vehicle_but_not_last() -> None:
    m = merge(trip(last=True), Change("rueckfahrt"), TODAY)
    assert (m.mode, m.last) == ("train", False)
    assert merge(trip(), Change("rueckfahrt", last=True), TODAY).last is True


def test_later_earlier_and_detail_use_the_shown_ride() -> None:
    assert merge(trip(), Change("spaeter"), TODAY).time_s == 9 * 3600 + 60
    assert merge(trip(), Change("frueher"), TODAY).time_s == 8 * 3600
    assert merge(trip(dep=1800), Change("frueher"), TODAY).time_s == 0
    m = merge(trip(short=True, last=True), Change("genauer"), TODAY)
    assert (m.time_s, m.last) == (9 * 3600, False)


def test_departures_drop_the_destination() -> None:
    assert merge(trip(), Change("abfahrten"), TODAY).dest is None


def test_time_past_today_moves_on_only_when_no_day_was_said() -> None:
    today = trip(day="2026-11-03")
    assert merge(today, Change("aendern", zeit_s=8 * 3600), TODAY, 18 * 3600).day == "2026-11-04"
    said = trip(day="2026-11-03", day_said=True)
    assert merge(said, Change("aendern", zeit_s=8 * 3600), TODAY, 18 * 3600).day == "2026-11-03"


def test_merge_leaves_the_old_state_untouched() -> None:
    t = trip()
    merge(t, Change("rueckfahrt"), TODAY)
    assert t.origin.gid == "at:1"


def test_state_survives_session_storage() -> None:
    t = trip(short=True)
    assert Trip.from_dict(t.to_dict()) == t
    assert Trip.from_dict({**t.to_dict(), "unbekannt": 1}) == t
    assert Trip.from_dict(trip(dest=None).to_dict()).dest is None
    assert Trip.from_dict({}) is None
    assert Trip.from_dict({"origin": "kaputt"}) is None


def test_numbers_from_dynamodb_become_plain_integers() -> None:
    import json
    from decimal import Decimal

    t = Trip.from_dict({**trip().to_dict(), "dep": Decimal(32400), "arr": Decimal(36000), "time_s": Decimal(18000)})
    assert t == trip() and json.dumps(t.to_dict())


def test_trip_text_names_only_what_is_known() -> None:
    assert trip_text(trip()) == "zug von Teststadt nach Bergdorf"
    assert trip_text(trip(dest=None, mode="any")) == "von Teststadt"
