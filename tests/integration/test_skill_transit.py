"""Fahrplan über den vollständigen Skill: freie Sätze, kurze Befehle, „und danach?“, KI-Werkzeug, Datenschutz."""

from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from conftest import attrs, ends_session, intent, make_harness, speech
from superkugel.config import Settings
from superkugel.services.usage import local_now
from superkugel.transit import service
from transit_fixture import package

NOW = dt.datetime(2026, 11, 3, 8, 10, tzinfo=ZoneInfo("Europe/Vienna"))  # Dienstag


@pytest.fixture(scope="module")
def paket(tmp_path_factory) -> bytes:
    return package(tmp_path_factory.mktemp("fp"))


@pytest.fixture(autouse=True)
def _fresh_cache():
    service.reset_cache()
    yield
    service.reset_cache()


def harness(paket: bytes, **settings):
    h = make_harness(Settings(progressive_after_s=5.0, address_form="du", home_stop="at:99:5", home_station="at:99:1",
                              **settings))
    h.services.now = lambda: NOW
    h.reads = []
    h.services.transit_reader = lambda key: (h.reads.append(key), paket)[1]
    h.store.put_item("TRANSIT", "CURRENT", {"key": "transit/fahrplan-test.zip", "start": "2026-11-01",
                                            "end": "2026-12-12"})
    return h


def chat(name: str, query: str, session: dict | None = None) -> dict:
    return intent(name, {"query": query}, session=session if session is not None else {})


def test_free_sentence_via_carrier_without_ai(paket, capsys) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt der nächste Zug nach Bergdorf"))
    s = speech(r)
    assert "Laut Fahrplan: um 9 Uhr 10 ab Teststadt Hauptbahnhof" in s and "9 Uhr 50" in s
    assert h.openai.requests == [] and ends_session(r) is False and "transit_last" in attrs(r)
    out = capsys.readouterr().out
    assert "transit_answer" in out and "Bergdorf" not in out and "Teststadt" not in out  # keine Orte im Log
    day = local_now(h.services.settings, NOW).strftime("%Y-%m-%d")
    assert h.store.get_stats(day)["transit"] == 1


def test_follow_up_gives_next_connection(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt der nächste Zug nach Bergdorf"))
    r2 = h.send(chat("ChatUndIntent", "danach", attrs(r)))
    assert "11 Uhr 10" in speech(r2) and h.openai.requests == []


def test_bare_intents_and_package_loaded_once(paket) -> None:
    h = harness(paket)
    r = h.send(intent("TransitNextBusIntent"))
    assert "Linie 7" in speech(r) or "Rufbus" in speech(r)
    r = h.send(intent("TransitNextTrainIntent"))
    assert "Regionalexpress" in speech(r)
    r = h.send(intent("TransitLastTrainIntent"))
    assert "als Letztes um 23 Uhr 50" in speech(r)
    r = h.send(intent("TransitLastBusIntent"))
    assert "als Letztes um 8 Uhr 50 Linie 7" in speech(r)  # Haltestelle gegenüber (Fußweg), letzte Abfahrt
    assert h.reads == ["transit/fahrplan-test.zip"]  # einmal pro Container, nicht pro Frage


def test_works_in_audiobooks_only_mode_but_not_in_maintenance(paket) -> None:
    from superkugel.services.ops import Mode

    h = harness(paket)
    h.params._mode = Mode.AUDIOBOOKS_ONLY
    assert "Laut Fahrplan" in speech(h.send(chat("ChatWieIntent", "komm ich nach Bergdorf")))
    h.params._mode = Mode.MAINTENANCE
    assert "Laut Fahrplan" not in speech(h.send(chat("ChatWieIntent", "komm ich nach Bergdorf")))


def test_ai_tool_fahrplan_answers_from_timetable(paket) -> None:
    h = harness(paket)
    args = {"ziel": "Bergdorf", "start": "", "zeit": "", "verkehrsmittel": "zug", "letzte": False}
    h.openai.replies.append((200, {"status": "completed", "output": [
        {"type": "function_call", "name": "fahrplan", "arguments": json.dumps(args), "call_id": "c1"}],
        "usage": {"input_tokens": 1, "output_tokens": 1}}))
    r = h.send(chat("ChatIchIntent", "möchte morgen meine Schwester besuchen, wann soll ich los"))
    assert "Laut Fahrplan" in speech(r) and "9 Uhr 10" in speech(r)
    tools = {t.get("name") for t in h.openai.requests[0]["body"]["tools"]}
    assert "fahrplan" in tools
    assert "Nenne nie selbst" in h.openai.requests[0]["body"]["instructions"]


def test_no_package_yet_is_honest(paket) -> None:
    h = harness(paket)
    h.store.delete_item("TRANSIT", "CURRENT")
    r = h.send(intent("TransitNextBusIntent"))
    assert "nicht zur Hand" in speech(r)


def test_broken_package_does_not_crash(paket) -> None:
    h = harness(paket)
    h.services.transit_reader = lambda key: b"kaputt"
    r = h.send(intent("TransitNextTrainIntent"))
    assert "nicht zur Hand" in speech(r)


def test_ordinary_chat_still_goes_to_ai(paket) -> None:
    h = harness(paket)
    h.openai.text("Ein guter Apfelstrudel braucht Zeit.")
    r = h.send(chat("ChatWieIntent", "geht ein Apfelstrudel"))
    assert "Apfelstrudel" in speech(r) and h.openai.requests
