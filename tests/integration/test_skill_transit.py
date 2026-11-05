"""Fahrplan über den vollständigen Skill: freie Sätze, kurze Befehle, „und danach?“, KI-Werkzeug, Datenschutz."""

from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from conftest import attrs, ends_session, intent, launch, make_harness, speech
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
    assert h.openai.requests == [] and ends_session(r) is False and "trip" in attrs(r)
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
    args = {"ziel": "Bergdorf", "naehe": "", "start": "", "zeit": "", "verkehrsmittel": "zug", "letzte": False}
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


# ------------------------------------------------------------------ v1.5
def _tool_reply(h, **args) -> None:
    full = {"ziel": "", "naehe": "", "start": "", "zeit": "", "verkehrsmittel": "", "letzte": False, **args}
    h.openai.replies.append((200, {"status": "completed", "output": [
        {"type": "function_call", "name": "fahrplan", "arguments": json.dumps(full), "call_id": "c1"}],
        "usage": {"input_tokens": 1, "output_tokens": 1}}))


def test_travel_sentence_without_bus_or_train_skips_ai(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatIchIntent", "möchte nach Bergdorf fahren"))
    assert "Laut Fahrplan" in speech(r) and h.openai.requests == []
    h.openai.text("Italien ist im Herbst wunderschön.")
    r = h.send(chat("ChatIchIntent", "fahre nächste Woche nach Italien"))  # kein Ort im Fahrplan → KI
    assert "Italien" in speech(r) and len(h.openai.requests) == 1


def test_same_name_asks_then_yes_no_or_hint(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt ein Zug nach Lindenau"))
    assert "Meinst du Lindenau Bahnhof?" in speech(r) and attrs(r)["pending"] == "transit_confirm"
    assert ends_session(r) is False
    yes = h.send(intent("AMAZON.YesIntent", session=attrs(r)))
    assert "Lindenau Bahnhof" in speech(yes) and "Laut Fahrplan" in speech(yes) and "pending" not in attrs(yes)
    no = h.send(intent("AMAZON.NoIntent", session=attrs(r)))
    assert "Oder meinst du Lindenau Kirche?" in speech(no)
    no2 = h.send(intent("AMAZON.NoIntent", session=attrs(no)))
    assert "genauer" in speech(no2) and "Sankt Johann in Tirol" in speech(no2)
    hint = h.send(chat("ChatDasIntent", "bei Bergdorf", attrs(r)))  # gleich die Auswahlhilfe sagen
    assert "Laut Fahrplan" in speech(hint) and "Lindenau Bahnhof" in speech(hint)
    assert h.openai.requests == []


def test_ai_tool_with_hint_center_and_original_sentence(paket) -> None:
    h = harness(paket)
    _tool_reply(h, ziel="Lindenau", naehe="Bergdorf", verkehrsmittel="zug")
    r = h.send(chat("ChatIchIntent", "will meine Schwester besuchen, die wohnt in Lindenau bei Bergdorf"))
    assert "Laut Fahrplan" in speech(r) and "Lindenau Bahnhof" in speech(r)
    _tool_reply(h, ziel="bei meiner Schwester")  # KI liefert Unsinn → der Originalsatz zählt
    r = h.send(chat("ChatIchIntent", "hab so Sehnsucht nach Lindenau bei Bergdorf"))
    assert "Lindenau Bahnhof" in speech(r)
    _tool_reply(h, ziel="Stadtzentrum")
    r = h.send(chat("ChatIchIntent", "brauch neue Schuhe, wie komm ich am besten hin"))
    assert "Teststadt Marktplatz" in speech(r)
    body = h.openai.requests[0]["body"]
    assert "Stadtzentrum" in body["instructions"] and "naehe" in json.dumps(body["tools"])


def test_brief_answer_then_genauer(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWieIntent", "komm ich nach Seeort"))
    assert "zweimal umsteigen" in speech(r) and "Bus 8" not in speech(r)
    r2 = h.send(intent("TransitDetailIntent", session=attrs(r)))
    assert "mit dem Bus 8" in speech(r2) and "2 Mal umsteigen" in speech(r2)
    r3 = h.send(chat("ChatUndIntent", "danach", attrs(r2)))
    assert "Laut Fahrplan" in speech(r3) and h.openai.requests == []
    h.openai.text("Gern: Der Strudel braucht Geduld.")
    r4 = h.send(intent("TransitDetailIntent"))  # ohne Fahrplanauskunft davor: Gespräch
    assert "Strudel" in speech(r4)


def test_shorter_answers_in_prompt(paket) -> None:
    h = harness(paket)
    h.openai.text("Gut.")
    h.send(chat("ChatWieIntent", "geht es dir"))
    assert "ein bis zwei kurze Sätze" in h.openai.requests[0]["body"]["instructions"]


# ------------------------------------------------------------------ v1.5.1 (Prüfbericht)
def _after_train(h) -> dict:
    return attrs(h.send(chat("ChatWannIntent", "fährt der nächste Zug nach Bergdorf")))


@pytest.mark.parametrize(("carrier", "query"), [
    ("ChatDannIntent", "mach ich mir einen Kaffee"),
    ("ChatDannIntent", "erzähl mir was über Kärnten"),
    ("ChatUndIntent", "danach geh ich schlafen"),
    ("ChatUndIntent", "dann hat sie gelacht"),
])
def test_ordinary_talk_after_a_timetable_answer_goes_to_ai(paket, carrier, query) -> None:
    h = harness(paket)
    session = _after_train(h)
    h.openai.text("Schön.")
    r = h.send(chat(carrier, query, session))
    assert "Schön" in speech(r) and len(h.openai.requests) == 1


def test_ai_answer_ends_the_timetable_topic(paket) -> None:
    h = harness(paket)
    session = _after_train(h)
    h.openai.text("Gern.")
    r = h.send(chat("ChatIchIntent", "mag Strudel", session))
    assert "trip" not in attrs(r)
    h.openai.text("Dann kommt die Füllung dran.")
    r = h.send(chat("ChatUndIntent", "danach", attrs(r)))
    assert "Füllung" in speech(r) and len(h.openai.requests) == 2


@pytest.mark.parametrize(("carrier", "query"), [
    ("ChatUndIntent", "der nächste Bus nach Seeort"),
    ("ChatUndIntent", "dann nach Seeort"),
    ("ChatDerIntent", "nächste nach Seeort"),
])
def test_new_destination_wins_over_the_old_one(paket, carrier, query) -> None:
    h = harness(paket)
    r = h.send(chat(carrier, query, _after_train(h)))
    assert "Seeort" in speech(r) and "Laut Fahrplan" in speech(r) and h.openai.requests == []


def test_other_vehicle_without_place_is_a_new_question(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatUndIntent", "der nächste Bus", _after_train(h)))
    assert "Linie 7" in speech(r) and "Regionalexpress" not in speech(r)


def test_follow_up_with_same_vehicle_still_works(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatUndIntent", "der nächste Zug", _after_train(h)))
    assert "11 Uhr 10" in speech(r)


def test_no_later_connection_after_the_last_one(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt der letzte Zug nach Bergdorf"))
    h.openai.text("Dann ist Feierabend.")
    r = h.send(chat("ChatUndIntent", "danach", attrs(r)))
    assert "Feierabend" in speech(r)


def test_date_and_relative_time_are_answered(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt am 20. November ein Zug nach Bergdorf"))
    assert "am Freitag, 20. November" in speech(r) and "9 Uhr 10" in speech(r)
    r = h.send(chat("ChatWannIntent", "fährt in zwei Stunden ein Zug nach Bergdorf"))
    assert "11 Uhr 10" in speech(r)
    r = h.send(chat("ChatWannIntent", "fährt ein Zug nach Bergdorf in zwei Stunden"))
    assert "11 Uhr 10" in speech(r)
    r = h.send(chat("ChatWannIntent", "fährt am 20. Dezember ein Zug nach Bergdorf"))
    assert "Am Sonntag, 20. Dezember hab ich noch keinen Fahrplan" in speech(r)


def test_vague_day_is_asked_for_and_the_answer_completes_the_question(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt nächste Woche ein Zug nach Bergdorf"))
    assert "Welchen Tag" in speech(r) and "Laut Fahrplan" not in speech(r)
    r = h.send(chat("ChatAmIntent", "Donnerstag", attrs(r)))
    assert "am Donnerstag, 12. November" in speech(r) and "9 Uhr 10" in speech(r) and h.openai.requests == []


def test_vague_day_then_other_talk_goes_to_ai(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt nächste Woche ein Zug nach Bergdorf"))
    h.openai.text("Gut.")
    r = h.send(chat("ChatIchIntent", "hab Hunger", attrs(r)))
    assert "Gut" in speech(r) and len(h.openai.requests) == 1


@pytest.mark.parametrize("sentence", [
    "will heute nicht in die Stadt fahren", "möchte nicht nach Bergdorf fahren", "geh zu Fuß in die Stadt",
])
def test_travel_sentences_that_are_no_trip_go_to_ai(paket, sentence) -> None:
    h = harness(paket)
    h.openai.text("Verstehe.")
    r = h.send(chat("ChatIchIntent", sentence))
    assert "Verstehe" in speech(r) and len(h.openai.requests) == 1


@pytest.mark.parametrize(("carrier", "query"), [
    ("ChatUndIntent", "zurück"),
    ("ChatUndIntent", "wie komm ich wieder heim"),
    ("ChatWieIntent", "komm ich zurück"),
    ("ChatUndIntent", "die Rückfahrt"),
])
def test_return_trip_after_the_arrival_without_ai(paket, carrier, query) -> None:
    h = harness(paket)
    r = h.send(chat(carrier, query, _after_train(h)))
    s = speech(r)
    assert "12 Uhr 30 ab Bergdorf Bahnhof" in s and "13 Uhr 10" in s and h.openai.requests == []


def test_return_trip_with_time_then_danach_and_back_again(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatUndIntent", "am Nachmittag zurück", _after_train(h)))
    assert "16 Uhr" in speech(r) and "ab Bergdorf Bahnhof" in speech(r)
    h2 = harness(paket)
    r = h2.send(chat("ChatUndIntent", "zurück", _after_train(h2)))
    r = h2.send(chat("ChatUndIntent", "danach", attrs(r)))
    assert "16 Uhr" in speech(r)
    r = h2.send(chat("ChatUndIntent", "zurück", attrs(r)))
    assert "ab Teststadt Hauptbahnhof" in speech(r)


def test_return_trip_keeps_the_day_of_the_outward_trip(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt am Freitag ein Zug nach Bergdorf"))
    r = h.send(chat("ChatUndIntent", "zurück", attrs(r)))
    assert "am Freitag, 6. November" in speech(r) and "12 Uhr 30" in speech(r)


def test_return_needs_a_journey_and_plain_talk_stays_talk(paket) -> None:
    h = harness(paket)
    h.openai.text("Wohin denn?")
    r = h.send(chat("ChatUndIntent", "zurück"))
    assert "Wohin" in speech(r)
    h = harness(paket)
    h.openai.text("Das ist lieb.")
    r = h.send(chat("ChatUndIntent", "ich ruf dich zurück", _after_train(h)))
    assert "lieb" in speech(r) and len(h.openai.requests) == 1


def test_timetable_waiting_for_its_start_is_used_from_that_day(paket) -> None:
    h = harness(paket)
    h.store.put_item("TRANSIT", "NEXT", {"key": "transit/neu.zip", "start": "2026-11-04", "end": "2026-12-12"})
    assert "Laut Fahrplan" in speech(h.send(intent("TransitNextTrainIntent")))
    assert h.reads == ["transit/fahrplan-test.zip"]  # 3.11.: noch der alte
    service.reset_cache()
    h.services.now = lambda: NOW + dt.timedelta(days=1)
    h.send(intent("TransitNextTrainIntent"))
    assert h.reads[-1] == "transit/neu.zip"


def test_thanks_ends_the_timetable_topic_without_an_answer_from_the_timetable(paket) -> None:
    h = harness(paket)
    r = h.send(intent("ThanksIntent", session=_after_train(h)))
    assert "Gerne" in speech(r) and "Laut Fahrplan" not in speech(r)
    assert "trip" not in attrs(r) and ends_session(r) is False and h.openai.requests == []


def test_thanks_after_a_question_about_a_place_ends_it_too(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt ein Zug nach Lindenau"))
    r = h.send(intent("ThanksIntent", session=attrs(r)))
    assert "Gerne" in speech(r) and "pending" not in attrs(r) and "transit_confirm" not in attrs(r)


def test_thanks_without_a_timetable_is_normal_talk(paket) -> None:
    h = harness(paket)
    h.openai.text("Bitte, gern geschehen.")
    r = h.send(intent("ThanksIntent", session={}))
    assert "gern geschehen" in speech(r) and len(h.openai.requests) == 1


@pytest.mark.parametrize(("carrier", "query"), [("ChatWiederIntent", "zurück"), ("ChatZurueckIntent", "um drei")])
def test_short_return_sentences_arrive_over_carrier_words(paket, carrier, query) -> None:
    h = harness(paket)
    r = h.send(chat(carrier, query, _after_train(h)))
    assert "ab Bergdorf Bahnhof" in speech(r) and h.openai.requests == []


# ------------------------------------------------------------------ v1.6: Reise-Stand
def test_time_only_keeps_the_day_of_the_question(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt am Freitag ein Zug nach Bergdorf"))
    r = h.send(chat("ChatGegenIntent", "zehn", attrs(r)))  # 10 Uhr liegt nicht in der Vergangenheit des Freitags
    assert "am Freitag, 6. November" in speech(r) and "11 Uhr 10" in speech(r) and h.openai.requests == []


def test_time_already_past_today_stays_on_the_chosen_day(paket) -> None:
    h = harness(paket)
    h.services.now = lambda: NOW.replace(hour=18)
    r = h.send(chat("ChatWannIntent", "fährt übermorgen ein Zug nach Bergdorf"))
    r = h.send(chat("ChatUndIntent", "gegen zehn", attrs(r)))
    assert "übermorgen um 11 Uhr 10" in speech(r)


def test_other_day_keeps_the_question_and_later_keeps_the_day(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt heute ein Zug nach Bergdorf"))
    r = h.send(chat("ChatUndIntent", "am Freitag", attrs(r)))
    assert "am Freitag, 6. November" in speech(r) and "Bergdorf" in speech(r)
    r = h.send(chat("ChatUndIntent", "danach", attrs(r)))
    assert "am Freitag, 6. November" in speech(r) and "11 Uhr 10" in speech(r)


def test_time_after_no_connection_keeps_the_trip(paket) -> None:
    h = harness(paket)
    r = h.send(chat("ChatWannIntent", "fährt am Samstag ein Zug nach Bergdorf"))
    assert "keine Verbindung" in speech(r) and "trip" in attrs(r)
    r = h.send(chat("ChatUndIntent", "am Freitag", attrs(r)))
    assert "am Freitag, 6. November" in speech(r) and "Laut Fahrplan" in speech(r)


def test_home_stop_is_only_a_marker_in_the_state(paket) -> None:
    h = harness(paket)
    t = attrs(h.send(chat("ChatWannIntent", "fährt der nächste Bus nach Bergdorf")))["trip"]
    assert t["origin"]["home"] is True and t["dest"]["home"] is False


def test_sentence_with_a_time_and_other_words_is_still_talk(paket) -> None:
    h = harness(paket)
    session = _after_train(h)
    h.openai.text("Schön.")
    r = h.send(chat("ChatIchIntent", "geh um acht schlafen", session))
    assert "Schön" in speech(r) and len(h.openai.requests) == 1


# ------------------------------------------------------------------ v1.6: Gedächtnis über „Stopp“
def test_trip_survives_stop_and_reopening(paket) -> None:
    h = harness(paket)
    session = _after_train(h)
    h.send(intent("AMAZON.StopIntent", session=session))
    r = h.send(launch())
    assert "Willkommen zurück" not in speech(r) and attrs(r)["trip"]["dest"]["name"] == "Bergdorf Bahnhof"
    r = h.send(chat("ChatUndIntent", "zurück", attrs(r)))
    assert "12 Uhr 30 ab Bergdorf Bahnhof" in speech(r) and h.openai.requests == []


def test_trip_is_found_when_a_question_opens_the_session(paket) -> None:
    h = harness(paket)
    _after_train(h)
    event = chat("ChatUndIntent", "gegen zehn")
    event["session"]["new"] = True
    assert "11 Uhr 10" in speech(h.send(event))


def test_trip_expires_and_thanks_or_ai_answer_end_it(paket) -> None:
    h = harness(paket)
    session = _after_train(h)
    h.send(intent("ThanksIntent", session=session))
    assert "trip" not in attrs(h.send(launch()))
    h = harness(paket)
    session = _after_train(h)
    h.openai.text("Gut.")
    h.send(chat("ChatIchIntent", "mag Strudel", session))
    assert "trip" not in attrs(h.send(launch()))
    h = harness(paket)
    _after_train(h)
    h.store.items[next(k for k in h.store.items if k[1] == "CONVERSATION")]["expires_at"] = 1
    assert "trip" not in attrs(h.send(launch()))


def test_stop_keeps_only_the_trip_not_the_conversation(paket) -> None:
    h = harness(paket)
    h.openai.text("Gern.")
    r = h.send(chat("ChatIchIntent", "mag Strudel"))
    session = attrs(h.send(chat("ChatWannIntent", "fährt der nächste Zug nach Bergdorf", attrs(r))))
    h.send(intent("AMAZON.StopIntent", session=session))
    r = h.send(launch())
    assert attrs(r).get("history") in (None, []) and "trip" in attrs(r) and "Wo waren wir" not in speech(r)
