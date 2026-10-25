"""Ausfallverhalten: Jeder Fehler endet mit kurzer Ansage und geschlossener Sitzung.

Geschlossene Sitzung = Alexa hört danach wieder ganz normal auf „Alexa, …“ (Timer, Wetter, …).
Eine direkte Weitergabe der laufenden Frage an die normale Alexa gibt es in der Plattform nicht.
"""

from __future__ import annotations

from conftest import attrs, audio_event, ends_session, intent, launch, make_harness, speech
from superkugel.config import Settings

FALLBACK = "Alexa aber ganz normal weiterverwenden"


def chat(session: dict | None = None) -> dict:
    return intent("ChatWasIntent", {"query": "ist das"}, session=session or {})


def test_first_timeout_offers_retry_second_ends_session(harness) -> None:
    harness.openai.error("timeout").error("timeout").error("timeout").error("timeout")
    r1 = harness.send(chat())
    assert "gehakt" in speech(r1) and ends_session(r1) is False
    r2 = harness.send(chat(attrs(r1)))
    assert FALLBACK in speech(r2) and ends_session(r2) is True


def test_auth_error_ends_session_immediately(harness) -> None:
    harness.openai.status(401)
    r = harness.send(chat())
    assert FALLBACK in speech(r) and ends_session(r) is True


def test_quota_exhausted_ends_session(harness) -> None:
    harness.openai.status(429, b'{"error":{"code":"insufficient_quota"}}')
    r = harness.send(chat())
    assert FALLBACK in speech(r) and ends_session(r) is True and len(harness.openai.requests) == 1


def test_missing_api_key(harness) -> None:
    harness.params._key = None
    r = harness.send(chat())
    assert FALLBACK in speech(r) and ends_session(r) is True


def test_circuit_breaker_skips_api_after_repeated_failures(harness) -> None:
    for _ in range(3):
        harness.openai.status(401)
        harness.send(chat())
    calls = len(harness.openai.requests)
    r = harness.send(chat())
    assert FALLBACK in speech(r) and ends_session(r) is True
    assert len(harness.openai.requests) == calls  # kein weiterer API-Aufruf, sofortige Antwort


def test_recovery_after_backend_returns(harness) -> None:
    harness.openai.status(401)
    assert ends_session(harness.send(chat())) is True
    harness.openai.text("Wieder da!")
    r = harness.send(chat())
    assert "Wieder da" in speech(r) and ends_session(r) is False


def test_usage_limit_blocks_ai_but_not_audiobooks() -> None:
    h = make_harness(Settings(daily_cost_limit_usd=0.000001, progressive_after_s=5))
    h.openai.text("Erste Antwort.", inp=10_000, out=1000)
    h.send(chat())
    r = h.send(chat())
    assert "Feierabend" in speech(r) and ends_session(r) is True and len(h.openai.requests) == 1


def test_library_outage_does_not_block_chat(harness) -> None:
    def boom(*a, **k):
        raise RuntimeError("DynamoDB nicht erreichbar")

    harness.store.list_books = boom  # type: ignore[method-assign]
    harness.store.list_progress = boom  # type: ignore[method-assign]
    harness.openai.text("Hallo")
    r = harness.send(chat())
    assert "Hallo" in speech(r) and ends_session(r) is False
    names = [t.get("name") for t in harness.openai.requests[0]["body"].get("tools", [])]
    assert "play_audiobook" not in names


def test_pause_works_even_if_storage_is_down(harness) -> None:
    from conftest import envelope

    def boom(*a, **k):
        raise RuntimeError("weg")

    harness.store.get_progress = boom  # type: ignore[method-assign]
    harness.store.list_books = boom  # type: ignore[method-assign]
    audio = {"token": "x|0", "offsetInMilliseconds": 5, "playerActivity": "PLAYING"}
    for name in ("AMAZON.PauseIntent", "AMAZON.StopIntent"):
        r = harness.send(intent(name, in_session=False, audio=audio))
        assert r["response"]["directives"][0]["type"] == "AudioPlayer.Stop", name
    r = harness.send(envelope({"type": "PlaybackController.PauseCommandIssued"}, audio=audio))
    assert r["response"]["directives"][0]["type"] == "AudioPlayer.Stop"


SLOW_BODY = (b'{"output":[{"type":"message","content":[{"type":"output_text","text":"spaet"}]}],'
             b'"usage":{"input_tokens":1000,"output_tokens":100}}')


def test_timed_out_call_is_still_counted() -> None:
    import time as _t

    from superkugel.conversation.llm import OpenAIClient

    h = make_harness(Settings(llm_timeout_s=0.6, request_deadline_s=1.0, progressive_after_s=5))

    def slow(url, headers, body, timeout):
        _t.sleep(1.0)
        return 200, SLOW_BODY

    h.services.llm_factory = lambda key: OpenAIClient(key, "m", transport=slow)
    r = h.send(chat())
    assert "gehakt" in speech(r)
    _t.sleep(1.0)
    # sofort vorsichtig gebucht (kein unzuverlässiges Nachzählen nach dem Einfrieren der Lambda)
    day = next(k for k in h.store.usage if k.startswith("DAY#"))
    assert h.store.get_usage(day).input_tokens >= 1000 and h.store.get_usage(day).searches == 1


def test_maintenance_blocks_audiobook_commands_but_not_pause(harness) -> None:
    from conftest import book
    from superkugel.services.ops import Mode

    harness.store.put_book(book())
    harness.params._mode = Mode.MAINTENANCE
    r = harness.send(intent("PlayAudiobookIntent", {"title": "kräuterbeet"}))
    assert "Pause" in speech(r) and not r["response"].get("directives")
    audio = {"token": "mord-im-kraeuterbeet|0", "offsetInMilliseconds": 5, "playerActivity": "PLAYING"}
    r = harness.send(intent("AMAZON.PauseIntent", in_session=False, audio=audio))
    assert r["response"]["directives"][0]["type"] == "AudioPlayer.Stop"


def test_lambda_handler_returns_emergency_response_when_setup_fails(monkeypatch) -> None:
    import superkugel.app as app
    from conftest import launch

    monkeypatch.setattr(app, "_SKILL", None)

    def broken(*a, **k):
        raise RuntimeError("init kaputt")

    monkeypatch.setattr(app, "default_services", broken)
    out = app.lambda_handler(launch(), None)
    assert out["response"]["shouldEndSession"] is True and "normal" in out["response"]["outputSpeech"]["ssml"]
    out = app.lambda_handler({"request": {"type": "AudioPlayer.PlaybackStarted"}}, None)
    assert out["response"] == {}


def test_unexpected_exception_in_launch_ends_session(harness) -> None:
    def boom() -> None:
        raise ValueError("kaputt")

    harness.params.mode = boom  # type: ignore[method-assign]
    r = harness.send(launch())
    assert FALLBACK in speech(r) and ends_session(r) is True


def test_exception_in_audio_event_returns_silent_empty_response(harness) -> None:
    def boom(*a, **k):
        raise RuntimeError("weg")

    harness.store.list_books = boom  # type: ignore[method-assign]
    r = harness.send(audio_event("PlaybackNearlyFinished", "x|0"))
    assert "outputSpeech" not in r["response"] and not r["response"].get("directives")


def test_unknown_intent_handled_like_fallback(harness) -> None:
    r = harness.send(intent("IntentDenEsNichtGibt", session={}))
    assert ends_session(r) is False and speech(r)


def test_no_conversation_content_in_logs(harness, capsys) -> None:
    harness.openai.text("Geheime Antwort über Gesundheit.")
    harness.send(intent("ChatIchIntent", {"query": "habe diabetes und nehme metformin"}, session={}))
    out = capsys.readouterr().out
    assert "metformin" not in out and "Geheime Antwort" not in out and "TESTUSER" not in out
    assert "llm_usage" in out
