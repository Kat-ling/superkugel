"""Über den vollständigen Skill: Morgengruß (1.2) und Hinweise auf Alexa für Erinnerungen, Radio, Rätsel (1.3)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from conftest import (
    DEVICE,
    USER,
    audio_event,
    book,
    directives,
    ends_session,
    envelope,
    intent,
    launch,
    make_harness,
)
from conftest import (
    speech as raw_speech,
)
from superkugel.config import Settings
from superkugel.services.logs import hash_user
from superkugel.services.usage import local_now

UID = hash_user(USER, DEVICE)
VIE = ZoneInfo("Europe/Vienna")
NOW = dt.datetime(2026, 10, 27, 9, 0, tzinfo=VIE)  # Dienstag 9:00


def speech(resp: dict) -> str:
    """Gesprochener Text ohne SSML-Tags."""
    import re

    return re.sub(r"\s{2,}", " ", re.sub(r"<[^>]+>", " ", raw_speech(resp))).replace(" .", ".").strip()


def harness(now: dt.datetime = NOW, **settings):
    h = make_harness(Settings(progressive_after_s=5.0, user_region="Kärnten", user_name="Maria", address_form="du", **settings))
    h.services.now = lambda: now
    return h


def chat(name: str, query: str, session: dict | None = None) -> dict:
    return intent(name, {"query": query}, session=session or {})


# ------------------------------------------------------------------ Morgengruß
def _fresh_context(h) -> None:
    now = NOW.timestamp()
    h.store.put_item("CONTEXT", "CURRENT", {
        "region": "Kärnten",
        "news": {"value": ["Schwerer Unfall auf der A2", "Nationalrat beschließt Budget"], "at": now},
        "regional": {"value": ["Neue Brücke über die Drau eröffnet"], "at": now},
        "weather": {"value": [{"date": "2026-10-27", "min": 3, "max": 14, "rain": 10, "desc": "sonnig"}], "at": now}})


def test_morning_briefing_once_without_ai() -> None:
    h = harness()
    _fresh_context(h)
    r = h.send(launch())
    s = speech(r)
    assert "Guten Morgen, Maria!" in s and "Heute ist Dienstag, der 27. Oktober." in s
    assert "sonnig, 3 bis 14 Grad" in s and "Neue Brücke über die Drau" in s and "Nationalrat" in s
    assert "Unfall" not in s and h.openai.requests == [] and ends_session(r) is False
    r2 = h.send(launch())
    assert "Guten Morgen" not in speech(r2) and "Servus Maria" in speech(r2)


def test_morning_not_after_eleven_and_switchable() -> None:
    h = harness(now=dt.datetime(2026, 10, 27, 11, 5, tzinfo=VIE))
    _fresh_context(h)
    assert "Guten Morgen" not in speech(h.send(launch()))
    h2 = harness()
    r = h2.send(intent("MorningOffIntent"))
    assert "lass ich den Morgengruß weg" in speech(r)
    assert "Guten Morgen" not in speech(h2.send(launch()))
    h2.send(intent("MorningOnIntent"))
    h2.services.now = lambda: NOW + dt.timedelta(days=1)
    assert "Guten Morgen" in speech(h2.send(launch()))
    h3 = harness(morning_briefing=False)
    assert "Guten Morgen" not in speech(h3.send(launch()))


# ------------------------------------------------------------------ Bestehendes bleibt
def test_existing_chat_and_search_choice_unaffected() -> None:
    h = harness()
    h.openai.text("Grüß dich.")
    r = h.send(chat("ChatWasIntent", "gibt's neues"))
    assert "Grüß dich" in speech(r)
    r = h.send(intent("ChooseResultIntent", {"number": "3"}, session={}))
    assert h.openai.requests  # Zahl ohne Dialog geht weiterhin ins Gespräch


# ------------------------------------------------------------------ Regressionen aus den Reviews (27.10.2026)


# ------------------------------------------------------------------ Erinnerungen, Radio, Rätsel → Alexa (1.3)
def test_reminder_radio_quiz_get_alexa_hint_without_ai_and_end_session() -> None:
    h = harness()
    cases = [
        (intent("RemindMeIntent", {"query": "morgen um zehn an den Arzt"}), "Alexa, erinnere mich"),
        (intent("ReminderIntent", {"date": "2026-10-29", "time": "15:00"}), "Alexa, erinnere mich"),
        (intent("ReminderIntent"), "Erinnerungen macht Alexa"),
        (intent("PlayRadioIntent"), "Alexa, spiel Ö3"),
        (intent("StartQuizIntent"), "Alexa, stell mir ein Rätsel"),
    ]
    for event, expected in cases:
        r = h.send(event)
        assert expected in speech(r) and ends_session(r) is True and not directives(r)
    assert h.openai.requests == []  # keine KI, also auch kein falsches Versprechen
    day = local_now(h.services.settings, NOW).strftime("%Y-%m-%d")
    assert h.store.get_stats(day)["alexa_hint"] == len(cases)


def test_hint_in_sie_form() -> None:
    h = make_harness(Settings(address_form="sie"))
    assert "sagen Sie dann einfach: Alexa, erinnere mich" in speech(h.send(intent("RemindMeIntent", {"query": "x"})))


def test_spiel_station_name_gives_radio_hint_but_books_and_shows_win() -> None:
    from superkugel.audiobooks import media

    h = harness()
    for said in ("Ö drei", "ö1", "FM vier", "Radio Kärnten", "den Sender Antenne"):
        r = h.send(intent("PlayAudiobookIntent", {"title": said}))
        assert "Radio spielt Alexa" in speech(r) and not directives(r), said
    h.store.put_book(book(book_id="hobbit", title="Der kleine Hobbit"))
    r = h.send(intent("PlayAudiobookIntent", {"title": "der kleine Hobbit"}))
    assert directives(r)[0]["audioItem"]["stream"]["token"].startswith("hobbit|")
    media.save_show(h.store, media.Show("tatort", "ARD Radio Tatort", "https://feed.example/rss", episodes=[
        media.Episode("e1", "Folge", "https://cdn.example/e1.mp3", 3_600_000, 1.0)]))
    r = h.send(intent("PlayAudiobookIntent", {"title": "Radio Tatort"}))
    assert "Radio spielt Alexa" not in speech(r) and directives(r)[0]["audioItem"]["stream"]["url"].endswith("e1.mp3")


def test_old_radio_token_on_device_does_not_break_book_commands() -> None:
    """Lief beim Update noch ein Sender aus 1.2 (Token radio-…), gehen Hörbuch-Befehle normal weiter."""
    h = harness()
    b = book()
    h.store.put_book(b)
    h.send(intent("PlayAudiobookIntent", {"title": "Mord im Kräuterbeet"}))
    old = {"token": "radio-oe1", "offsetInMilliseconds": 0, "playerActivity": "PLAYING"}
    r = h.send(intent("AMAZON.PauseIntent", in_session=False, audio=old))
    assert directives(r)[0]["type"] == "AudioPlayer.Stop"
    r = h.send(intent("AMAZON.ResumeIntent", in_session=False, audio={**old, "playerActivity": "STOPPED"}))
    assert directives(r)[0]["audioItem"]["stream"]["token"].startswith(f"{b.book_id}|")
    for ev in (audio_event("PlaybackStopped", "radio-oe1", 5_000), audio_event("PlaybackFailed", "radio-oe1", 0)):
        assert "outputSpeech" not in h.send(ev)["response"]
    r = h.send(envelope({"type": "PlaybackController.NextCommandIssued"}, audio=old))
    assert "outputSpeech" not in r["response"]


def test_help_without_removed_features_in_both_forms() -> None:
    from superkugel.speech.texts import text

    for form in ("du", "sie"):
        h = text(form, "help")
        assert "Radio" not in h and "erinner" not in h.lower() and "Rätsel" not in h and "Hörbuch" in h


def test_ai_has_no_radio_or_reminder_tools_and_prompt_points_to_alexa() -> None:
    h = harness()
    h.openai.text("Grüß dich.")
    h.send(chat("ChatWasIntent", "gibt's neues"))
    body = h.openai.requests[0]["body"]
    names = {t.get("name") for t in body.get("tools", [])}
    assert not names & {"play_radio", "set_reminder"}
    assert "Für Erinnerungen, Radio, Rätsel" in body["instructions"]

