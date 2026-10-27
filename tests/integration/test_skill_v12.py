"""v1.2 über den vollständigen Skill: Erinnerungen, Radio, Morgengruß, Rätsel, Konflikte mit bestehenden Intents."""

from __future__ import annotations

import datetime as dt
import json
import time
from zoneinfo import ZoneInfo

from conftest import (
    DEVICE,
    USER,
    attrs,
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


class FakeReminders:
    """Gefälschte Alexa Reminders API (kein Netz)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next: list[tuple[int, object] | Exception] = []
        self.alerts: list[dict] = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "body": json.loads(body) if body else None, "timeout": timeout})
        if self.next:
            r = self.next.pop(0)
            if isinstance(r, Exception):
                raise r
            code, data = r
            return code, json.dumps(data).encode()
        if method == "GET":
            return 200, json.dumps({"alerts": self.alerts, "totalCount": len(self.alerts)}).encode()
        return (201, json.dumps({"alertToken": "tok-1", "status": "ON"}).encode()) if method == "POST" else (200, b"")


def speech(resp: dict) -> str:
    """Gesprochener Text ohne SSML-Tags."""
    import re

    return re.sub(r"\s{2,}", " ", re.sub(r"<[^>]+>", " ", raw_speech(resp))).replace(" .", ".").strip()


def harness(now: dt.datetime = NOW, **settings):
    h = make_harness(Settings(progressive_after_s=5.0, user_region="Kärnten", user_name="Maria", address_form="du", **settings))
    h.reminders = FakeReminders()
    h.services.reminder_transport = h.reminders
    h.services.now = lambda: now
    return h


def chat(name: str, query: str, session: dict | None = None) -> dict:
    return intent(name, {"query": query}, session=session or {})


# ------------------------------------------------------------------ Erinnerungen
def test_reminder_full_flow_with_confirmation(capsys) -> None:
    h = harness()
    r = h.send(intent("RemindMeIntent", {"query": "morgen um zehn an den Arzt"}))
    assert "Ich erinner dich morgen, Mittwoch, um 10 Uhr an: den Arzt. Passt das?" in speech(r)
    assert ends_session(r) is False and attrs(r)["pending"] == "reminder_confirm"
    assert h.reminders.calls == []  # vor dem „ja“ wird nichts angelegt
    r2 = h.send(intent("AMAZON.YesIntent", session=attrs(r)))
    call = h.reminders.calls[0]
    assert call["method"] == "POST" and call["timeout"] <= 3.0
    assert call["body"]["trigger"]["scheduledTime"] == "2026-10-28T10:00:00.000"
    assert "Erledigt" in speech(r2) and "pending" not in attrs(r2) and "reminder" not in attrs(r2)
    out = capsys.readouterr().out
    assert "arzt" not in out.lower()  # Erinnerungstext nie in Logs
    assert not any(k[0] == f"USER#{UID}" and "arzt" in json.dumps(v).lower() for k, v in h.store.items.items())


def test_reminder_asks_for_time_then_text_and_accepts_chat_answers() -> None:
    h = harness()
    r = h.send(intent("RemindMeIntent", {"query": "an die Tabletten"}))
    assert "Wann soll ich dich erinnern" in speech(r) and attrs(r)["pending"] == "reminder_time"
    r = h.send(chat("ChatMorgenIntent", "um acht in der früh", attrs(r)))
    assert "morgen, Mittwoch, um 8 Uhr an: die Tabletten" in speech(r)
    h2 = harness()
    r = h2.send(intent("RemindMeIntent", {"query": "morgen um zehn"}))
    assert "Woran soll ich dich erinnern" in speech(r)
    r = h2.send(chat("ChatAnIntent", "den Friseur", attrs(r)))
    assert "an: den Friseur" in speech(r) and attrs(r)["pending"] == "reminder_confirm"


def test_reminder_slots_intent_answers_when_question() -> None:
    h = harness()
    r = h.send(intent("RemindMeIntent", {"query": "an die Post"}))
    r = h.send(intent("SetReminderIntent", {"date": "2026-10-29", "time": "15:00"}, session=attrs(r)))
    assert "übermorgen, Donnerstag, um 15 Uhr an: die Post" in speech(r)


def test_reminder_no_cancels_and_correction() -> None:
    h = harness()
    r = h.send(intent("RemindMeIntent", {"query": "morgen um zehn an den Arzt"}))
    r2 = h.send(intent("AMAZON.NoIntent", session=attrs(r)))
    assert "Gut, dann nicht" in speech(r2) and h.reminders.calls == [] and "pending" not in attrs(r2)
    r3 = h.send(chat("ChatNeinIntent", "um elf", attrs(r)))  # „nein, um elf“ → korrigiert nachfragen
    assert "um 11 Uhr an: den Arzt" in speech(r3) and attrs(r3)["pending"] == "reminder_confirm"


def test_reminder_past_and_repeat_rejected() -> None:
    h = harness()
    r = h.send(intent("RemindMeIntent", {"query": "heute um sieben in der früh an den Bus"}))
    assert "schon vorbei" in speech(r) and attrs(r)["pending"] == "reminder_time"
    r = h.send(intent("RemindMeIntent", {"query": "jeden Tag um acht an die Tabletten"}))
    assert "Wiederkehrende Erinnerungen kann ich noch nicht" in speech(r) and h.reminders.calls == []


def _with_scope(event: dict, status: str) -> dict:
    event["context"]["System"]["user"]["permissions"] = {
        "scopes": {"alexa::alerts:reminders:skill:readwrite": {"status": status}}}
    return event


def test_missing_permission_sends_consent_card() -> None:
    h = harness()
    r = h.send(_with_scope(intent("RemindMeIntent", {"query": "morgen um zehn an den Arzt"}), "DENIED"))
    card = r["response"]["card"]
    assert card["type"] == "AskForPermissionsConsent"
    assert card["permissions"] == ["alexa::alerts:reminders:skill:readwrite"]
    assert "Alexa-App" in speech(r) and ends_session(r) is True
    # Berechtigung erteilt → normaler Ablauf
    r = harness().send(_with_scope(intent("RemindMeIntent", {"query": "morgen um zehn an den Arzt"}), "GRANTED"))
    assert "Passt das?" in speech(r)


def test_api_401_on_create_sends_card_and_timeout_ends_friendly(capsys) -> None:
    h = harness()
    r = h.send(intent("RemindMeIntent", {"query": "morgen um zehn an den Arzt"}))
    h.reminders.next.append((401, {"code": "UNAUTHORIZED"}))
    r2 = h.send(intent("AMAZON.YesIntent", session=attrs(r)))
    assert r2["response"]["card"]["type"] == "AskForPermissionsConsent" and ends_session(r2) is True
    from superkugel.reminders.api import ReminderError

    h.reminders.next.append(ReminderError("failed"))
    r3 = h.send(intent("AMAZON.YesIntent", session=attrs(r)))
    assert "hat gerade nicht geklappt" in speech(r3) and ends_session(r3) is True
    assert "ReminderApiError" in capsys.readouterr().out
    assert h.store.get_stats(local_now(h.services.settings, NOW).strftime("%Y-%m-%d")).get("reminder_errors") == 1


def _alert(token: str, when: str, text: str) -> dict:
    return {"alertToken": token, "status": "ON", "trigger": {"scheduledTime": when, "timeZoneId": "Europe/Vienna"},
            "alertInfo": {"spokenInfo": {"content": [{"locale": "de-DE", "text": text}]}}}


def test_list_and_delete_with_number_and_confirmation() -> None:
    h = harness()
    h.reminders.alerts = [_alert("a", "2026-10-28T10:00:00.000", "den arzt"),
                          _alert("b", "2026-10-29T15:00:00.000", "die post"),
                          _alert("old", "2026-10-20T15:00:00.000", "vorbei"),
                          _alert("admin", "2026-10-28T08:00:00.000", "fremd")]  # am Echo des Admins angelegt
    h.store.put_item(f"USER#{UID}", "REMINDERS", {"tokens": ["a", "b", "old"]})
    r = h.send(intent("ListRemindersIntent"))
    assert "1. morgen, Mittwoch, um 10 Uhr an den arzt" in speech(r) and "vorbei" not in speech(r)
    assert "fremd" not in speech(r)  # nur Erinnerungen dieses Geräts (gemeinsames Admin-Konto)
    r = h.send(intent("DeleteReminderIntent"))
    assert "Welche soll ich löschen" in speech(r)
    r = h.send(intent("ChooseResultIntent", {"ordinal": "zweite"}, session=attrs(r)))
    assert "Soll ich die Erinnerung" in speech(r) and "die post" in speech(r)
    r = h.send(intent("AMAZON.YesIntent", session=attrs(r)))
    assert h.reminders.calls[-1]["method"] == "DELETE" and h.reminders.calls[-1]["url"].endswith("/b")
    assert "gelöscht" in speech(r)


def test_ai_tool_set_reminder_uses_her_sentence() -> None:
    h = harness()
    h.openai.replies.append((200, {"output": [{"type": "function_call", "name": "set_reminder",
                                               "arguments": json.dumps({"request": "irgendwas"}), "call_id": "c"}],
                                   "usage": {"input_tokens": 1, "output_tokens": 1}}))
    r = h.send(chat("ChatKannstDuIntent", "mich morgen um neun an den Zahnarzt erinnern"))
    assert "morgen, Mittwoch, um 9 Uhr" in speech(r) and "Passt das?" in speech(r)
    tools = [t.get("name") for t in h.openai.requests[0]["body"]["tools"]]
    assert "set_reminder" in tools and "play_radio" in tools


# ------------------------------------------------------------------ Radio
def _radio_ctx(token: str = "radio-oe1", activity: str = "PLAYING") -> dict:
    return {"token": token, "offsetInMilliseconds": 0, "playerActivity": activity}


def test_play_radio_by_synonym_does_not_touch_bookmark() -> None:
    h = harness()
    b = book()
    h.store.put_book(b)
    h.send(intent("PlayAudiobookIntent", {"title": "Mord im Kräuterbeet"}))
    h.send(audio_event("PlaybackStopped", f"{b.book_id}|1", 123_000))
    before = h.store.get_progress(UID, b.book_id)
    r = h.send(intent("PlayRadioIntent", {"station": "Ö eins"}))
    d = directives(r)[0]
    assert d["type"] == "AudioPlayer.Play" and d["playBehavior"] == "REPLACE_ALL"
    assert d["audioItem"]["stream"]["token"] == "radio-oe1" and d["audioItem"]["stream"]["offsetInMilliseconds"] == 0
    assert d["audioItem"]["stream"]["url"].startswith("https://") and "Ö1" in speech(r)
    for ev in (audio_event("PlaybackStarted", "radio-oe1", 0), audio_event("PlaybackStopped", "radio-oe1", 999_000)):
        h.send(ev)
    h.send(intent("AMAZON.PauseIntent", in_session=False, audio=_radio_ctx()))
    assert h.store.get_progress(UID, b.book_id) == before
    assert h.store.get_state(UID)["book_id"] == b.book_id
    r = h.send(intent("ResumeAudiobookIntent", audio=_radio_ctx(activity="STOPPED")))
    assert directives(r)[0]["audioItem"]["stream"]["token"] == f"{b.book_id}|1"  # „Hörbuch weiter“ = Hörbuch


def test_radio_pause_resume_next_previous_and_seek() -> None:
    h = harness()
    r = h.send(intent("AMAZON.PauseIntent", in_session=False, audio=_radio_ctx()))
    assert directives(r)[0]["type"] == "AudioPlayer.Stop"
    r = h.send(intent("AMAZON.ResumeIntent", in_session=False, audio=_radio_ctx(activity="STOPPED")))
    assert directives(r)[0]["audioItem"]["stream"]["token"] == "radio-oe1"  # live neu gestartet
    r = h.send(intent("AMAZON.NextIntent", in_session=False, audio=_radio_ctx()))
    assert directives(r)[0]["audioItem"]["stream"]["token"] == "radio-oe3"
    r = h.send(intent("AMAZON.PreviousIntent", in_session=False, audio=_radio_ctx()))
    assert directives(r)[0]["audioItem"]["stream"]["token"] == "radio-ktn"  # Regionalsender steht vorne
    r = h.send(intent("RewindIntent", in_session=False, audio=_radio_ctx()))
    assert "live" in speech(r) and not directives(r)
    r = h.send(intent("WhatIsPlayingIntent", in_session=False, audio=_radio_ctx()))
    assert "Ö1" in speech(r)


def test_playback_controller_on_radio() -> None:
    h = harness()
    ctx = _radio_ctx("radio-ktn")
    r = h.send(envelope({"type": "PlaybackController.NextCommandIssued"}, audio=ctx))
    assert directives(r)[0]["audioItem"]["stream"]["token"] == "radio-oe1" and "outputSpeech" not in r["response"]
    r = h.send(envelope({"type": "PlaybackController.PlayCommandIssued"}, audio=ctx))
    assert directives(r)[0]["audioItem"]["stream"]["token"] == "radio-ktn"


def test_resume_any_restarts_radio_when_it_was_last() -> None:
    h = harness()
    b = book()
    h.store.put_book(b)
    h.send(intent("PlayAudiobookIntent", {"title": "Mord im Kräuterbeet"}))
    h.send(audio_event("PlaybackStopped", f"{b.book_id}|0", 5_000))
    time.sleep(0.01)
    h.send(intent("PlayRadioIntent", {"station": "Radio Kärnten"}))
    r = h.send(intent("AMAZON.ResumeIntent", in_session=False))  # kein AudioPlayer-Kontext
    assert directives(r)[0]["audioItem"]["stream"]["token"] == "radio-ktn"


def test_dead_station_honest_and_play_title_route() -> None:
    h = harness()
    h.store.put_item("RADIO", "HEALTH", {"down": ["oe3"], "checked": 4, "at": time.time()})
    r = h.send(intent("PlayRadioIntent", {"station": "Ö drei"}))
    assert "nicht erreichbar" in speech(r) and not directives(r) and ends_session(r) is True
    r = h.send(intent("PlayAudiobookIntent", {"title": "Radio Kärnten"}))  # landet oft bei „spiel {title}“
    assert directives(r)[0]["audioItem"]["stream"]["token"] == "radio-ktn"
    r = h.send(intent("PlayRadioIntent", {"station": "Radio Luxemburg"}))
    assert "hab ich leider nicht" in speech(r) and "Radio Kärnten" in speech(r)
    r = h.send(intent("PlayRadioIntent"))
    assert "Welchen Sender" in speech(r)


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


# ------------------------------------------------------------------ Rätsel
def test_quiz_flow_right_wrong_give_up_and_stop() -> None:
    from superkugel.quiz.items import BY_ID

    h = harness()
    r = h.send(intent("StartQuizIntent"))
    a = attrs(r)
    assert "machen wir ein Rätsel" in speech(r) and a["pending"] == "quiz"
    item = BY_ID[a["quiz"]["id"]]
    assert item.question.split("?")[0][:20] in speech(r) or item.question[:20] in speech(r)
    r = h.send(intent("QuizAnswerIntent", {"answer": item.answers[0]}, session=a))
    assert any(p in speech(r) for p in ("richtig", "stimmt")) and "Nächstes Rätsel" in speech(r)
    a = attrs(r)
    r = h.send(intent("QuizAnswerIntent", {"answer": "Zwetschkenröster"}, session=a))
    assert "nicht ganz" in speech(r) and "Tipp" in speech(r)
    r = h.send(intent("QuizAnswerIntent", {"answer": "Zwetschkenröster"}, session=attrs(r)))
    assert "Die Antwort ist" in speech(r) and "Nächstes Rätsel" in speech(r)
    r = h.send(intent("QuizAnswerIntent", {"answer": "weiß nicht"}, session=attrs(r)))
    assert "Die Antwort ist" in speech(r)
    r = h.send(intent("AMAZON.StopIntent", session=attrs(r)))
    assert "Du hast heute 1 gewusst" in speech(r) and ends_session(r) is False  # still weiter zuhören
    assert "reprompt" not in r["response"]


def test_quiz_numbers_via_choose_intent_and_fallback_is_patient() -> None:
    from superkugel.quiz.items import BY_ID

    h = harness()
    a = attrs(h.send(intent("StartQuizIntent")))
    a["quiz"] = {"id": "r15", "tries": 0, "asked": 1, "kind": "rechnen"}
    r = h.send(intent("ChooseResultIntent", {"number": "75"}, session=a))
    assert "richtig" in speech(r) or "stimmt" in speech(r)
    r2 = h.send(intent("AMAZON.FallbackIntent", session=attrs(r)))
    assert "Antwort" in speech(r2) and attrs(r2).get("misunderstood") is None
    assert BY_ID  # Sammlung geladen


def test_quiz_no_repeat_across_sessions() -> None:
    h = harness()
    ids = set()
    for _ in range(12):
        ids.add(attrs(h.send(intent("StartQuizIntent")))["quiz"]["id"])
    assert len(ids) == 12


def test_quiz_explain_uses_ai_within_budget() -> None:
    h = harness()
    a = attrs(h.send(intent("StartQuizIntent")))
    h.openai.text("Weil …")
    r = h.send(chat("ChatErklaerMirIntent", "das", a))
    assert "Weil" in speech(r)
    assert "Die Antwort ist" in h.openai.requests[0]["body"]["input"][-1]["content"]


# ------------------------------------------------------------------ Bestehendes bleibt
def test_existing_chat_and_search_choice_unaffected() -> None:
    h = harness()
    h.openai.text("Grüß dich.")
    r = h.send(chat("ChatWasIntent", "gibt's neues"))
    assert "Grüß dich" in speech(r)
    r = h.send(intent("ChooseResultIntent", {"number": "3"}, session={}))
    assert h.openai.requests  # Zahl ohne Dialog geht weiterhin ins Gespräch


def test_quiz_answer_intent_outside_quiz_goes_to_chat() -> None:
    h = harness()
    r = h.send(intent("QuizAnswerIntent", {"answer": "klagenfurt"}))
    assert "nicht ganz verstanden" in speech(r) and h.openai.requests == []  # kein Sammelbecken → keine KI-Kosten
    assert attrs(r)["misunderstood"] == 1


def test_help_mentions_new_features_in_both_forms() -> None:
    from superkugel.speech.texts import text

    for form in ("du", "sie"):
        h = text(form, "help")
        assert "Radio" in h and "erinner" in h.lower() and "Rätsel" in h


# ------------------------------------------------------------------ Regressionen aus den Reviews (27.10.2026)
def test_yes_with_correction_reconfirms_instead_of_creating() -> None:
    h = harness()
    r = h.send(intent("RemindMeIntent", {"query": "morgen um zehn an den Arzt"}))
    r = h.send(chat("ChatJaIntent", "aber um elf", attrs(r)))
    assert "um 11 Uhr an: den Arzt. Passt das?" in speech(r) and h.reminders.calls == []
    r = h.send(chat("ChatNaIntent", "klar", attrs(r)))  # Kärntnerisch „na klar“ = ja
    assert "Erledigt" in speech(r)
    assert h.reminders.calls[-1]["body"]["trigger"]["scheduledTime"].startswith("2026-10-28T11:00")
    r = h.send(intent("RemindMeIntent", {"query": "morgen um zehn an den Arzt"}))
    r = h.send(chat("ChatNaIntent", "", attrs(r)))  # „na“ allein = nein
    assert "Gut, dann nicht" in speech(r)


def test_correction_does_not_overwrite_text() -> None:
    h = harness()
    r = h.send(intent("RemindMeIntent", {"query": "morgen um zehn an den Arzt"}))
    r = h.send(chat("ChatDannIntent", "lieber um elf", attrs(r)))
    assert "an: den Arzt" in speech(r) and "lieber" not in speech(r)


def test_radio_intent_does_not_swallow_dialog_answers_or_books() -> None:
    h = harness()
    a = attrs(h.send(intent("StartQuizIntent")))
    a["quiz"] = {"id": "w16", "tries": 0, "asked": 1, "kind": "wissen"}
    r = h.send(intent("PlayRadioIntent", {"station": "Wien"}, session=a))
    assert "richtig" in speech(r) or "stimmt" in speech(r)
    r = h.send(intent("RemindMeIntent", {"query": "morgen um zehn"}))
    r = h.send(intent("PlayRadioIntent", {"station": "Tabletten"}, session=attrs(r)))
    assert "an: Tabletten. Passt das?" in speech(r)
    h.store.put_book(book(book_id="hobbit", title="Der kleine Hobbit"))
    r = h.send(intent("PlayRadioIntent", {"station": "der kleine Hobbit"}))
    assert directives(r)[0]["audioItem"]["stream"]["token"].startswith("hobbit|")
    r = h.send(intent("PlayRadioIntent", {"station": "Radio Luxemburg"}))
    assert "hab ich leider nicht" in speech(r)


def test_stale_radio_token_does_not_hijack_book_commands() -> None:
    h = harness()
    b = book()
    h.store.put_book(b)
    h.send(intent("PlayAudiobookIntent", {"title": "Mord im Kräuterbeet"}))
    stale = _radio_ctx(activity="STOPPED")
    r = h.send(intent("NextChapterIntent", audio=stale))
    assert directives(r)[0]["audioItem"]["stream"]["token"] == f"{b.book_id}|1"
    r = h.send(intent("WhatIsPlayingIntent", audio=stale))
    assert "Mord im Kräuterbeet" in speech(r)
    r = h.send(intent("AMAZON.StartOverIntent", in_session=False, audio=_radio_ctx()))
    assert directives(r)[0]["audioItem"]["stream"]["token"] == "radio-oe1"  # Radio: von vorn = live neu


def test_time_intent_only_inside_dialog_and_bare_hour() -> None:
    h = harness()
    r = h.send(intent("ReminderTimeIntent", {"time": "08:00"}))
    assert "nicht ganz verstanden" in speech(r)  # kein ungefragter Erinnerungsdialog
    r = h.send(intent("RemindMeIntent", {"query": "an die Post"}))
    r = h.send(intent("ChooseResultIntent", {"number": "10"}, session=attrs(r)))  # „Wann?“ – „zehn“
    assert "heute um 10 Uhr an: die Post" in speech(r)


def test_dialog_fallback_gives_up_and_cancel_keeps_skill_open() -> None:
    h = harness()
    r = h.send(intent("RemindMeIntent", {"query": "morgen um zehn"}))
    r = h.send(intent("AMAZON.FallbackIntent", session=attrs(r)))
    assert "Woran" in speech(r)
    r = h.send(intent("AMAZON.FallbackIntent", session=attrs(r)))
    assert "nicht ganz verstanden" in speech(r) and "pending" not in attrs(r)
    r = h.send(intent("RemindMeIntent", {"query": "morgen um zehn an den Arzt"}))
    r = h.send(intent("AMAZON.CancelIntent", session=attrs(r)))
    assert "Gut, dann nicht" in speech(r) and ends_session(r) is False and h.reminders.calls == []


def test_yes_in_quiz_is_not_a_wrong_try() -> None:
    h = harness()
    a = attrs(h.send(intent("StartQuizIntent")))
    r = h.send(intent("AMAZON.YesIntent", session=a))
    assert "Antwort" in speech(r) and attrs(r)["quiz"]["tries"] == 0


def test_no_reminder_text_anywhere_in_storage_also_via_ai_tool() -> None:
    h = harness()
    h.openai.replies.append((200, {"output": [{"type": "function_call", "name": "set_reminder",
                                               "arguments": json.dumps({"request": "x"}), "call_id": "c"}],
                                   "usage": {"input_tokens": 1, "output_tokens": 1}}))
    r = h.send(chat("ChatKannstDuIntent", "mich morgen um neun an den Zahnarzt erinnern"))
    h.send(intent("AMAZON.YesIntent", session=attrs(r)))
    assert h.reminders.calls[-1]["method"] == "POST"
    dump = json.dumps({str(k): v for k, v in h.store.items.items()}, ensure_ascii=False).lower()
    assert "zahnarzt" not in dump
    assert h.store.get_item(f"USER#{UID}", "REMINDERS")["tokens"] == ["tok-1"]  # nur die Kennung
