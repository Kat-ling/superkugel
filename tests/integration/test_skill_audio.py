"""Hörbuch-Befehle und AudioPlayer-Ereignisse über den vollständigen Skill."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import DEVICE, USER, attrs, audio_event, book, directives, ends_session, envelope, intent, speech
from superkugel.audiobooks.models import Progress
from superkugel.services.logs import hash_user

UID = hash_user(USER, DEVICE)


def playing(token: str, offset: int, activity: str = "PLAYING") -> dict:
    return {"token": token, "offsetInMilliseconds": offset, "playerActivity": activity}


def setup(h) -> None:
    h.store.put_book(book())
    h.store.put_book(book("tod-am-woerthersee", "Tod am Wörthersee", "Hans Huber", ("regionalkrimi",),
                          imported_at="2026-10-20T00:00:00+00:00"))


def play_of(r: dict) -> dict:
    d = directives(r)
    assert d and d[0]["type"] == "AudioPlayer.Play", r
    return d[0]


def test_play_title_fuzzy_starts_at_beginning(harness) -> None:
    setup(harness)
    r = harness.send(intent("PlayAudiobookIntent", {"title": "das kräuterbeet"}))
    d = play_of(r)
    assert d["playBehavior"] == "REPLACE_ALL" and d["audioItem"]["stream"]["offsetInMilliseconds"] == 0
    assert d["audioItem"]["stream"]["url"].startswith("https://")
    assert d["audioItem"]["stream"]["token"] == "mord-im-kraeuterbeet|0"
    assert ends_session(r) is True and "Mord im Kräuterbeet" in speech(r)


def test_pause_saves_position_and_resume_continues(harness) -> None:
    setup(harness)
    harness.send(intent("PlayAudiobookIntent", {"title": "kräuterbeet"}))
    r = harness.send(intent("AMAZON.PauseIntent", in_session=False, audio=playing("mord-im-kraeuterbeet|1", 125_000)))
    assert directives(r)[0]["type"] == "AudioPlayer.Stop"
    p = harness.store.get_progress(UID, "mord-im-kraeuterbeet")
    assert (p.chapter, p.offset_ms) == (1, 125_000)
    r = harness.send(intent("AMAZON.ResumeIntent", in_session=False))
    s = play_of(r)["audioItem"]["stream"]
    assert s["token"] == "mord-im-kraeuterbeet|1" and s["offsetInMilliseconds"] == 120_000


def test_resume_my_krimi_after_restart_uses_stored_progress(harness) -> None:
    setup(harness)
    harness.store.put_progress(UID, Progress("tod-am-woerthersee", chapter=2, offset_ms=300_000, started=True, updated_at=9))
    harness.store.put_state(UID, {"book_id": "tod-am-woerthersee"})
    # "Spiel meinen Krimi weiter" – kann als ResumeAudiobookIntent oder PlayAudiobookIntent ankommen
    for req in (intent("ResumeAudiobookIntent"), intent("PlayAudiobookIntent", {"title": "meinen krimi weiter"})):
        s = play_of(harness.send(req))["audioItem"]["stream"]
        assert s["token"] == "tod-am-woerthersee|2" and s["offsetInMilliseconds"] == 295_000


def test_rewind_and_forward_from_audio_context(harness) -> None:
    setup(harness)
    r = harness.send(intent("RewindIntent", in_session=False, audio=playing("mord-im-kraeuterbeet|1", 10_000, "PAUSED")))
    s = play_of(r)["audioItem"]["stream"]
    assert s["token"] == "mord-im-kraeuterbeet|0" and s["offsetInMilliseconds"] == 580_000
    r = harness.send(intent("AMAZON.PreviousIntent", in_session=False, audio=playing("mord-im-kraeuterbeet|1", 100_000)))
    assert play_of(r)["audioItem"]["stream"]["offsetInMilliseconds"] == 70_000
    r = harness.send(intent("ForwardIntent", in_session=False, audio=playing("mord-im-kraeuterbeet|1", 100_000)))
    assert play_of(r)["audioItem"]["stream"]["offsetInMilliseconds"] == 130_000


def test_next_and_previous_chapter(harness) -> None:
    setup(harness)
    r = harness.send(intent("AMAZON.NextIntent", in_session=False, audio=playing("mord-im-kraeuterbeet|0", 5_000)))
    assert play_of(r)["audioItem"]["stream"]["token"] == "mord-im-kraeuterbeet|1"
    r = harness.send(intent("PreviousChapterIntent", in_session=False, audio=playing("mord-im-kraeuterbeet|1", 5_000)))
    assert play_of(r)["audioItem"]["stream"]["token"] == "mord-im-kraeuterbeet|0"
    r = harness.send(intent("NextChapterIntent", in_session=False, audio=playing("mord-im-kraeuterbeet|2", 5_000)))
    assert "letzte Kapitel" in speech(r) and not directives(r)


def test_stop_while_playing_pauses_instead_of_goodbye(harness) -> None:
    setup(harness)
    r = harness.send(intent("AMAZON.StopIntent", in_session=False, audio=playing("mord-im-kraeuterbeet|0", 9_000)))
    assert directives(r)[0]["type"] == "AudioPlayer.Stop"
    assert harness.store.get_progress(UID, "mord-im-kraeuterbeet").offset_ms == 9_000


def test_genre_and_newest(harness) -> None:
    setup(harness)
    r = harness.send(intent("PlayNewestIntent", {"genre": "gartenkrimi"}))
    assert play_of(r)["audioItem"]["stream"]["token"].startswith("mord-im-kraeuterbeet")
    r = harness.send(intent("PlayGenreIntent", {"genre": "krimi"}))
    assert play_of(r)  # irgendein Krimi
    r = harness.send(intent("PlayAudiobookIntent", {"title": "meinen neuen gartenkrimi"}))
    assert play_of(r)["audioItem"]["stream"]["token"].startswith("mord-im-kraeuterbeet")


def test_list_books_by_genre(harness) -> None:
    setup(harness)
    r = harness.send(intent("ListAudiobooksIntent", {"genre": "krimi"}, session={}))
    assert "Tod am Wörthersee" in speech(r) and "Mord im Kräuterbeet" in speech(r) and ends_session(r) is False


def test_unknown_title_and_empty_library(harness) -> None:
    r = harness.send(intent("PlayAudiobookIntent", {"title": "harry potter"}))
    assert "noch kein Hörbuch" in speech(r)
    setup(harness)
    harness.openai.text("Harry Potter hab ich leider nicht in deiner Bibliothek.")
    r = harness.send(intent("PlayAudiobookIntent", {"title": "harry potter"}))
    assert "leider nicht" in speech(r) and not directives(r)
    assert "Mord im Kräuterbeet" in harness.openai.requests[-1]["body"]["instructions"]


def test_unknown_title_resolved_by_ai_from_library(harness) -> None:
    setup(harness)
    harness.openai.tool("tod-am-woerthersee", "Gern, der Wörthersee-Krimi.")
    r = harness.send(intent("PlayAudiobookIntent", {"title": "den krimi vom see"}))
    assert play_of(r)["audioItem"]["stream"]["token"].startswith("tod-am-woerthersee")


def test_unknown_title_without_ai_says_not_found(harness) -> None:
    from superkugel.services.ops import Mode

    setup(harness)
    harness.params._mode = Mode.AUDIOBOOKS_ONLY
    r = harness.send(intent("PlayAudiobookIntent", {"title": "harry potter"}))
    assert "hab ich leider nicht" in speech(r) and not harness.openai.requests


def test_playback_events_track_progress_and_enqueue(harness) -> None:
    setup(harness)
    r = harness.send(audio_event("PlaybackStarted", "mord-im-kraeuterbeet|0", 0))
    assert "outputSpeech" not in r["response"]
    r = harness.send(audio_event("PlaybackNearlyFinished", "mord-im-kraeuterbeet|0", 590_000))
    d = play_of(r)
    assert d["playBehavior"] == "ENQUEUE" and d["audioItem"]["stream"]["expectedPreviousToken"] == "mord-im-kraeuterbeet|0"
    harness.send(audio_event("PlaybackFinished", "mord-im-kraeuterbeet|0", 600_000))
    assert harness.store.get_progress(UID, "mord-im-kraeuterbeet").chapter == 1
    harness.send(audio_event("PlaybackStopped", "mord-im-kraeuterbeet|1", 42_000))
    assert harness.store.get_progress(UID, "mord-im-kraeuterbeet").offset_ms == 42_000


def test_expired_link_playback_failed_replays_with_fresh_url(harness) -> None:
    setup(harness)
    ev = audio_event("PlaybackFailed", "mord-im-kraeuterbeet|1", 0,
                     error={"type": "MEDIA_ERROR_SERVICE_UNAVAILABLE", "message": "403"},
                     currentPlaybackState={"token": "mord-im-kraeuterbeet|1", "offsetInMilliseconds": 77_000,
                                           "playerActivity": "PLAYING"})
    r = harness.send(ev)
    s = play_of(r)["audioItem"]["stream"]
    assert s["offsetInMilliseconds"] == 77_000 and "sig" in s["url"]
    harness.send(ev)
    r = harness.send(ev)
    assert not directives(r)  # nach 2 Versuchen aufhören statt Endlosschleife


def test_failed_enqueued_chapter_retries_that_chapter(harness) -> None:
    setup(harness)
    ev = audio_event("PlaybackFailed", "mord-im-kraeuterbeet|2", 0, error={"type": "MEDIA_ERROR_UNKNOWN", "message": "x"},
                     currentPlaybackState={"token": "mord-im-kraeuterbeet|1", "offsetInMilliseconds": 599_000,
                                           "playerActivity": "PLAYING"})
    s = play_of(harness.send(ev))["audioItem"]["stream"]
    assert s["token"] == "mord-im-kraeuterbeet|2" and s["offsetInMilliseconds"] == 0


def test_playback_controller_buttons(harness) -> None:
    setup(harness)
    ev = envelope({"type": "PlaybackController.NextCommandIssued"}, audio=playing("mord-im-kraeuterbeet|0", 1000))
    assert play_of(harness.send(ev))["audioItem"]["stream"]["token"] == "mord-im-kraeuterbeet|1"
    ev = envelope({"type": "PlaybackController.PauseCommandIssued"}, audio=playing("mord-im-kraeuterbeet|1", 3000))
    assert directives(harness.send(ev))[0]["type"] == "AudioPlayer.Stop"


def test_loop_shuffle_not_supported(harness) -> None:
    r = harness.send(intent("AMAZON.ShuffleOnIntent", in_session=False))
    assert "leider nicht" in speech(r)


def test_whats_playing(harness) -> None:
    setup(harness)
    r = harness.send(intent("WhatIsPlayingIntent", in_session=False, audio=playing("tod-am-woerthersee|1", 1)))
    assert "Tod am Wörthersee" in speech(r) and "Kapitel 2 von 3" in speech(r)


def test_session_ended_and_system_exception_are_silent(harness) -> None:
    r = harness.send(envelope({"type": "SessionEndedRequest", "reason": "EXCEEDED_MAX_REPROMPTS"}, session={}))
    assert "outputSpeech" not in r["response"]
    r = harness.send(envelope({"type": "System.ExceptionEncountered",
                               "error": {"type": "INVALID_RESPONSE", "message": "x"},
                               "cause": {"requestId": "r"}}))
    assert "outputSpeech" not in r["response"]


def test_progress_is_separate_per_echo_device(harness) -> None:
    """Gleiches Amazon-Konto (Admin), zwei Echos: getrennte Lesezeichen."""
    setup(harness)
    harness.store.put_progress(UID, Progress("tod-am-woerthersee", chapter=2, offset_ms=300_000, started=True))
    harness.store.put_state(UID, {"book_id": "tod-am-woerthersee"})
    other = intent("ResumeAudiobookIntent")
    other["context"]["System"]["device"]["deviceId"] = "echo-im-buero"
    r = harness.send(other)
    assert "kein angefangenes" in speech(r) and not directives(r)
    assert play_of(harness.send(intent("ResumeAudiobookIntent")))["audioItem"]["stream"]["token"] == "tod-am-woerthersee|2"


def jump(name: str, value: str, token: str, offset: int) -> dict:
    return intent(name, {"duration": value}, audio=playing(token, offset, "STOPPED"))


def test_jump_back_over_several_chapters(harness) -> None:
    setup(harness)
    r = harness.send(jump("JumpBackIntent", "PT11M", "mord-im-kraeuterbeet|2", 60_000))
    s = play_of(r)["audioItem"]["stream"]
    assert s["token"] == "mord-im-kraeuterbeet|1" and s["offsetInMilliseconds"] == 0
    p = harness.store.get_progress(UID, "mord-im-kraeuterbeet")
    assert (p.chapter, p.offset_ms) == (1, 0)


def test_jump_forward_over_several_chapters(harness) -> None:
    setup(harness)
    r = harness.send(jump("JumpForwardIntent", "PT21M", "mord-im-kraeuterbeet|0", 60_000))
    s = play_of(r)["audioItem"]["stream"]
    assert s["token"] == "mord-im-kraeuterbeet|2" and s["offsetInMilliseconds"] == 120_000


def test_jump_past_the_end_keeps_playing_at_the_same_place(harness) -> None:
    setup(harness)
    r = harness.send(jump("JumpForwardIntent", "PT1H", "mord-im-kraeuterbeet|1", 90_000))
    s = play_of(r)["audioItem"]["stream"]
    assert s["token"] == "mord-im-kraeuterbeet|1" and s["offsetInMilliseconds"] == 90_000
    assert "So weit" in speech(r)


def test_unclear_duration_asks_again_without_moving(harness) -> None:
    setup(harness)
    r = harness.send(jump("JumpBackIntent", "?", "mord-im-kraeuterbeet|1", 90_000))
    assert not directives(r) and ends_session(r) is False and "zehn Minuten zurück" in speech(r)


def started(h, chapter: int = 1, offset: int = 90_000, finished: bool = False) -> None:
    setup(h)
    h.store.put_progress(UID, Progress("mord-im-kraeuterbeet", chapter=chapter, offset_ms=offset, started=True,
                                       finished=finished, updated_at=9))
    h.store.put_state(UID, {"book_id": "mord-im-kraeuterbeet"})


def test_restart_asks_first_and_yes_starts_the_whole_book(harness) -> None:
    started(harness)
    r = harness.send(intent("RestartBookIntent"))
    assert not directives(r) and ends_session(r) is False and "Mord im Kräuterbeet" in speech(r)
    p = harness.store.get_progress(UID, "mord-im-kraeuterbeet")
    assert (p.chapter, p.offset_ms) == (1, 90_000)
    r = harness.send(intent("AMAZON.YesIntent", session=attrs(r)))
    s = play_of(r)["audioItem"]["stream"]
    assert s["token"] == "mord-im-kraeuterbeet|0" and s["offsetInMilliseconds"] == 0
    p = harness.store.get_progress(UID, "mord-im-kraeuterbeet")
    assert (p.chapter, p.offset_ms, p.finished) == (0, 0, False)


def test_restart_no_keeps_the_place(harness) -> None:
    started(harness)
    r = harness.send(intent("RestartBookIntent"))
    r = harness.send(intent("AMAZON.NoIntent", session=attrs(r)))
    assert not directives(r) and ends_session(r) is True and "bleibt" in speech(r)
    p = harness.store.get_progress(UID, "mord-im-kraeuterbeet")
    assert (p.chapter, p.offset_ms) == (1, 90_000)


def test_restart_answer_in_a_longer_sentence(harness) -> None:
    started(harness)
    r = harness.send(intent("RestartBookIntent"))
    r2 = harness.send(intent("ChatJaIntent", {"query": "bitte"}, session=attrs(r)))
    assert play_of(r2)["audioItem"]["stream"]["token"] == "mord-im-kraeuterbeet|0"
    assert not harness.openai.requests
    r3 = harness.send(intent("ChatNeinIntent", {"query": "lieber nicht"}, session=attrs(r)))
    assert not directives(r3) and "bleibt" in speech(r3) and not harness.openai.requests


def test_restart_without_a_place_to_lose_needs_no_question(harness) -> None:
    started(harness, chapter=2, offset=0, finished=True)
    r = harness.send(intent("RestartBookIntent"))
    assert play_of(r)["audioItem"]["stream"]["token"] == "mord-im-kraeuterbeet|0"


def test_restart_by_title_and_in_free_speech(harness) -> None:
    started(harness)
    harness.store.put_progress(UID, Progress("tod-am-woerthersee", chapter=1, offset_ms=5_000, started=True, updated_at=9))
    r = harness.send(intent("PlayAudiobookIntent", {"title": "tod am wörthersee von vorne"}))
    assert not directives(r) and "Tod am Wörthersee" in speech(r)
    assert attrs(r)["pending"] == "restart_book"
    r = harness.send(intent("ChatDasIntent", {"query": "hörbuch von vorne"}))
    assert not directives(r) and attrs(r)["pending"] == "restart_book" and not harness.openai.requests


def test_restart_stale_book_is_harmless(harness) -> None:
    started(harness)
    r = harness.send(intent("AMAZON.YesIntent", session={"pending": "restart_book", "restart_book_id": "gibt-es-nicht"}))
    assert not directives(r)


def test_ordinary_talk_after_the_question_drops_it(harness) -> None:
    started(harness)
    r = harness.send(intent("RestartBookIntent"))
    harness.openai.text("Gut.")
    r = harness.send(intent("ChatWieIntent", {"query": "geht es dir"}, session=attrs(r)))
    assert "pending" not in attrs(r)


def test_navigation_commands_are_in_the_model() -> None:
    model = Path(__file__).parents[2] / "skill-package" / "interactionModels" / "custom" / "de-DE.json"
    data = json.loads(model.read_text(encoding="utf-8"))
    intents = {i["name"]: i for i in data["interactionModel"]["languageModel"]["intents"]}
    assert "{duration} zurück" in intents["JumpBackIntent"]["samples"]
    assert "{duration} vor" in intents["JumpForwardIntent"]["samples"]
    assert intents["JumpBackIntent"]["slots"] == [{"name": "duration", "type": "AMAZON.DURATION"}]
    assert "fang das buch von vorne an" in intents["RestartBookIntent"]["samples"]
