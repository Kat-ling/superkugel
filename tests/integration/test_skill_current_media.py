"""Tagesaktuelles (A+B), Lieblingssendungen und Mediensuche über den vollständigen Skill."""

from __future__ import annotations

from conftest import DEVICE, USER, attrs, directives, ends_session, intent, launch, make_harness, speech
from superkugel.audiobooks import media
from superkugel.audiobooks.media import Episode, SearchHit, Show
from superkugel.config import Settings
from superkugel.services.logs import hash_user

UID = hash_user(USER, DEVICE)


def chat(name: str, query: str, session: dict | None = None) -> dict:
    return intent(name, {"query": query}, session=session or {})


def tool_names(h) -> list[str]:
    return [t.get("name") or t.get("type") for t in h.openai.requests[-1]["body"].get("tools", [])]


def add_show(h, show_id: str = "kein-mucks", name: str = "Kein Mucks!") -> Show:
    show = Show(show_id, name, "https://feed.example/rss", genres=["krimi"],
                episodes=[Episode("e2", "Neue Folge", "https://cdn.example/e2.mp3", 3_600_000, 2.0),
                          Episode("e1", "Alte Folge", "https://cdn.example/e1.mp3", 3_600_000, 1.0)])
    media.save_show(h.store, show)
    return show


class FakeIndex:
    def __init__(self, key: str, secret: str) -> None:
        self.calls: list[str] = []

    def search(self, term: str, limit: int = 3, timeout: float = 3.0) -> list[SearchHit]:
        FakeIndex.last_term = term
        return [SearchHit(11, "Krimi-Hörspiel der Woche", "ARD"), SearchHit(12, "Gartenkrimis", "ORF")]

    def latest_episodes(self, feed_id: int, limit: int = 5, timeout: float = 3.0) -> list[Episode]:
        return [Episode(f"x{feed_id}", "Folge 7", f"https://cdn.example/{feed_id}.mp3", 1_000_000, 9.0)]


# ------------------------------------------------------------------ Gespräch ohne Nachfrage
def test_answer_has_no_reprompt_but_keeps_listening(harness) -> None:
    harness.openai.text("Inflation heißt, dass das Geld weniger wert ist.")
    r = harness.send(chat("ChatWasIntent", "ist inflation"))
    assert ends_session(r) is False and "reprompt" not in r["response"]
    assert "KEINE Rückfrage" in harness.openai.requests[0]["body"]["instructions"]


def test_texts_say_ratschen_not_plaudern() -> None:
    from superkugel.speech.styles import STYLES
    from superkugel.speech.texts import TEXTS

    blob = " ".join(" ".join(v) for v in TEXTS.values()) + " ".join(
        " ".join(s.greeting.values()) for s in STYLES.values())
    assert "plaudern" not in blob.lower() and "ratschen" in blob.lower()


# ------------------------------------------------------------------ A + B im Prompt / Tools
def test_context_block_and_web_search_tool_with_austrian_location() -> None:
    h = make_harness(Settings(user_city="Teststadt", user_region="Kärnten", progressive_after_s=5))
    h.store.put_item("CONTEXT", "CURRENT", {"news": {"value": ["ORF-Schlagzeile"], "at": __import__("time").time()},
                                            "region": "Kärnten"})
    h.openai.text("Laut ORF …")
    h.send(chat("ChatWasIntent", "gibt's neues"))
    body = h.openai.requests[0]["body"]
    assert "ORF-Schlagzeile" in body["instructions"] and "Websuche" in body["instructions"]
    ws = next(t for t in body["tools"] if t["type"] == "web_search")
    # Datenschutz: keine Stadt an die Websuche, nur Land + Bundesland + Zeitzone
    assert ws["user_location"] == {"type": "approximate", "country": "AT", "timezone": "Europe/Vienna",
                                   "region": "Kärnten"}
    assert "Teststadt" not in body["instructions"]
    assert "<<<DATEN" in body["instructions"] and body["instructions"].index("ORF-Schlagzeile") > \
        body["instructions"].index("<<<DATEN")
    assert ws["search_context_size"] == "low" and body["max_tool_calls"] == 1


def test_web_search_removed_when_daily_quota_used() -> None:
    h = make_harness(Settings(web_search_daily_limit=1, progressive_after_s=5))
    h.openai.replies.append((200, {"output": [
        {"type": "web_search_call", "status": "completed", "action": {"queries": ["skispringen ergebnis"]}},
        {"type": "message", "content": [{"type": "output_text", "text": "Gewonnen hat …"}]}],
        "usage": {"input_tokens": 3000, "output_tokens": 50}}))
    h.openai.text("Heute kann ich nicht mehr nachschauen.")
    h.send(chat("ChatWerIntent", "hat gestern gewonnen"))
    h.send(chat("ChatWerIntent", "hat heute gewonnen"))
    assert "web_search" not in tool_names(h)
    assert "keine Websuche mehr möglich" in h.openai.requests[-1]["body"]["instructions"]
    day = next(k for k in h.store.usage if k.startswith("DAY#"))
    assert h.store.get_usage(day).searches == 1 and h.store.get_usage(day).cost_usd >= 0.012


def test_privacy_metric_when_search_contains_name(capsys) -> None:
    h = make_harness(Settings(user_name="Maria", progressive_after_s=5))
    h.openai.replies.append((200, {"output": [
        {"type": "web_search_call", "action": {"queries": ["Maria Arzttermin"]}},
        {"type": "message", "content": [{"type": "output_text", "text": "…"}]}]}))
    h.send(chat("ChatWannIntent", "hab ich meinen termin"))
    out = capsys.readouterr().out
    assert "SearchQueryContainedName" in out and "Arzttermin" not in out


# ------------------------------------------------------------------ Lieblingssendungen
def test_play_show_latest_then_resume(harness) -> None:
    add_show(harness)
    r = harness.send(intent("PlayShowIntent", {"show": "kein mucks"}))
    d = directives(r)[0]["audioItem"]["stream"]
    assert d["url"] == "https://cdn.example/e2.mp3" and d["token"] == "pod-kein-mucks-e2|0"
    assert "Neue Folge" in speech(r)
    harness.send(intent("AMAZON.PauseIntent", in_session=False,
                        audio={"token": "pod-kein-mucks-e2|0", "offsetInMilliseconds": 600_000, "playerActivity": "PLAYING"}))
    # „spiel Kein Mucks“ (ohne „neueste“) setzt fort …
    r = harness.send(intent("PlayAudiobookIntent", {"title": "kein mucks"}))
    s = directives(r)[0]["audioItem"]["stream"]
    assert s["token"] == "pod-kein-mucks-e2|0" and s["offsetInMilliseconds"] == 595_000 and "weiter" in speech(r)


def test_newest_episode_request_plays_newest_even_if_older_started(harness) -> None:
    add_show(harness)
    from superkugel.audiobooks.models import Progress

    harness.store.put_progress(UID, Progress("pod-kein-mucks-e1", offset_ms=1000, started=True))
    r = harness.send(intent("PlayShowIntent", {"show": "kein mucks"}))
    assert directives(r)[0]["audioItem"]["stream"]["token"] == "pod-kein-mucks-e2|0"


def test_episode_events_and_resume_via_weiter(harness) -> None:
    from conftest import audio_event

    add_show(harness)
    harness.send(intent("PlayShowIntent", {"show": "kein mucks"}))
    harness.send(audio_event("PlaybackStopped", "pod-kein-mucks-e2|0", 120_000))
    r = harness.send(intent("AMAZON.ResumeIntent", in_session=False))  # „Alexa, weiter“
    assert directives(r)[0]["audioItem"]["stream"]["url"] == "https://cdn.example/e2.mp3"


def test_paused_podcast_does_not_replace_my_audiobook(harness) -> None:
    from conftest import audio_event, book

    harness.store.put_book(book())
    harness.send(intent("PlayAudiobookIntent", {"title": "kräuterbeet"}))
    harness.send(audio_event("PlaybackStopped", "mord-im-kraeuterbeet|0", 5000))
    add_show(harness)
    harness.send(intent("PlayShowIntent", {"show": "kein mucks"}))
    harness.send(audio_event("PlaybackStopped", "pod-kein-mucks-e2|0", 60_000))
    r = harness.send(intent("ResumeAudiobookIntent"))
    assert directives(r)[0]["audioItem"]["stream"]["token"] == "mord-im-kraeuterbeet|0"
    r = harness.send(launch())
    assert "Hörbuch" in speech(r)  # Angebot bezieht sich auf das Hörbuch, nicht auf die Folge


def test_play_title_also_finds_shows(harness) -> None:
    add_show(harness)
    r = harness.send(intent("PlayAudiobookIntent", {"title": "kein mucks"}))
    assert directives(r)[0]["audioItem"]["stream"]["token"].startswith("pod-kein-mucks")


def test_list_shows_without_follow_up(harness) -> None:
    add_show(harness)
    r = harness.send(intent("ListShowsIntent", session={}))
    assert "Kein Mucks!" in speech(r) and "reprompt" not in r["response"]


def test_llm_play_show_tool(harness) -> None:
    add_show(harness)
    harness.openai.replies.append((200, {"output": [{"type": "function_call", "name": "play_show",
                                                     "arguments": '{"show_id": "kein-mucks"}'}]}))
    r = harness.send(chat("ChatHastDuIntent", "was spannendes zum hören"))
    assert directives(r)[0]["audioItem"]["stream"]["url"].endswith("e2.mp3")
    assert "play_show" in tool_names(harness)


# ------------------------------------------------------------------ Freie Mediensuche
def test_search_choose_and_play(harness) -> None:
    harness.params.podcast_creds = ("k", "s")
    harness.services.media_client_factory = FakeIndex
    r = harness.send(intent("SearchMediaIntent", {"query": "krimi hörspiel"}, session={}))
    assert "die erste: Krimi-Hörspiel der Woche" in speech(r) and attrs(r)["pending"] == "choose_media"
    r = harness.send(intent("ChooseResultIntent", {"ordinal": "zweite"}, session=attrs(r)))
    s = directives(r)[0]["audioItem"]["stream"]
    assert s["url"] == "https://cdn.example/12.mp3" and s["token"] == "pod-pi12-x12|0"


def test_choose_by_spiel_die_erste(harness) -> None:
    harness.params.podcast_creds = ("k", "s")
    harness.services.media_client_factory = FakeIndex
    r = harness.send(intent("SearchMediaIntent", {"query": "krimi"}, session={}))
    r = harness.send(intent("PlayAudiobookIntent", {"title": "die erste"}, session=attrs(r)))
    assert directives(r)[0]["audioItem"]["stream"]["url"].endswith("/11.mp3")


def test_search_without_key_and_limit(harness) -> None:
    r = harness.send(intent("SearchMediaIntent", {"query": "krimi"}, session={}))
    assert "suchen kann ich gerade nicht" in speech(r)
    h = make_harness(Settings(media_search_daily_limit=1, progressive_after_s=5))
    h.params.podcast_creds = ("k", "s")
    h.services.media_client_factory = FakeIndex
    h.send(intent("SearchMediaIntent", {"query": "a"}, session={}))
    r = h.send(intent("SearchMediaIntent", {"query": "b"}, session={}))
    assert "genug gesucht" in speech(r)


def test_search_media_tool_only_with_key(harness) -> None:
    harness.openai.text("x").text("y")
    harness.send(chat("ChatWasIntent", "ist los"))
    assert "search_media" not in tool_names(harness)
    harness.params.podcast_creds = ("k", "s")
    harness.send(chat("ChatWasIntent", "ist los"))
    assert "search_media" in tool_names(harness)


def test_refresh_event_runs_without_alexa(monkeypatch) -> None:
    import superkugel.app as app

    called = {}
    monkeypatch.setattr(app, "run_refresh", lambda: called.setdefault("ok", True) and {"ok": True})
    out = app.lambda_handler({"superkugel": "refresh_context"}, None)
    assert out == {"ok": True} and called["ok"]


def test_request_after_refresh_does_not_inherit_cold_start_clock(monkeypatch) -> None:
    # Live gefunden: Der stündliche Abruf wärmt die Lambda; die erste Alexa-Anfrage danach startete die Uhr beim
    # Modul-Laden (35 s früher) und brach sofort mit Zeitüberschreitung ab.
    import superkugel.app as app

    seen = []
    monkeypatch.setattr(app, "_COLD_START_PENDING", True)
    monkeypatch.setattr(app, "_MODULE_LOADED", app.time.monotonic() - 35)
    monkeypatch.setattr(app, "run_refresh", lambda: seen.append(app.REQUEST_STARTED.get()) or {"ok": True})
    monkeypatch.setattr(app, "_SKILL", object())
    monkeypatch.setattr(app, "handle_event", lambda *a: seen.append(app.REQUEST_STARTED.get()) or {})
    app.lambda_handler({"superkugel": "refresh_context"}, None)
    app.lambda_handler({"request": {"type": "LaunchRequest"}}, None)
    assert app.time.monotonic() - seen[0] >= 35  # erster Aufruf zählt den Kaltstart
    assert app.time.monotonic() - seen[1] < 5  # danach eigene Uhr pro Anfrage


def test_launch_still_works(harness) -> None:
    assert ends_session(harness.send(launch())) is False



def test_choice_needs_real_choice_phrase(harness) -> None:
    harness.params.podcast_creds = ("k", "s")
    harness.services.media_client_factory = FakeIndex
    r = harness.send(intent("SearchMediaIntent", {"query": "krimi"}, session={}))
    harness.openai.text("Die drei Fragezeichen hab ich nicht.")
    r2 = harness.send(intent("PlayAudiobookIntent", {"title": "die drei fragezeichen"}, session=attrs(r)))
    assert not (directives(r2) and directives(r2)[0]["audioItem"]["stream"]["url"].endswith("/12.mp3"))
    r3 = harness.send(intent("ChooseResultIntent", {"ordinal": "letzte"}, session=attrs(r)))
    assert directives(r3)[0]["audioItem"]["stream"]["url"].endswith("/12.mp3")  # 2 Treffer → letzte = 2


def test_number_outside_search_goes_to_chat(harness) -> None:
    harness.openai.text("Zwei ist eine schöne Zahl.")
    r = harness.send(intent("ChooseResultIntent", {"number": "2"}, session={}))
    assert "schöne Zahl" in speech(r)


def test_chat_intent_during_search_tries_choice_first(harness) -> None:
    harness.params.podcast_creds = ("k", "s")
    harness.services.media_client_factory = FakeIndex
    r = harness.send(intent("SearchMediaIntent", {"query": "krimi"}, session={}))
    r = harness.send(intent("ChatDieIntent", {"query": "zweite"}, session=attrs(r)))
    assert directives(r)[0]["audioItem"]["stream"]["url"].endswith("/12.mp3")


def test_no_during_search_cancels(harness) -> None:
    harness.params.podcast_creds = ("k", "s")
    harness.services.media_client_factory = FakeIndex
    r = harness.send(intent("SearchMediaIntent", {"query": "krimi"}, session={}))
    r = harness.send(intent("AMAZON.NoIntent", session=attrs(r)))
    assert "dann nicht" in speech(r) and not harness.openai.requests and "pending" not in attrs(r)


def test_search_query_never_contains_name() -> None:
    h = make_harness(Settings(user_name="Maria", progressive_after_s=5))
    h.params.podcast_creds = ("k", "s")
    h.services.media_client_factory = FakeIndex
    h.send(intent("SearchMediaIntent", {"query": "hörspiel für maria"}, session={}))
    assert "maria" not in FakeIndex.last_term.lower()


def test_share_name_off_keeps_name_local() -> None:
    h = make_harness(Settings(user_name="Maria", share_name_with_ai=False, address_form="du", progressive_after_s=5))
    assert "Maria" in speech(h.send(launch()))
    h.openai.text("Gern.")
    h.send(chat("ChatWasIntent", "ist los"))
    assert "Maria" not in h.openai.requests[0]["body"]["instructions"]


def test_slow_total_time_counts_including_timeout(capsys) -> None:
    import time as _t

    from superkugel.conversation.llm import OpenAIClient

    h = make_harness(Settings(llm_timeout_s=0.6, request_deadline_s=0.7, progressive_after_s=5, slow_answer_ms=100))

    def slow(url, headers, body, timeout):
        _t.sleep(1.0)
        return 200, b'{"output":[]}'

    h.services.llm_factory = lambda key: OpenAIClient(key, "m", transport=slow)
    h.send(chat("ChatWasIntent", "ist los"))
    assert "SlowAnswer" in capsys.readouterr().out


def test_tool_search_respects_remaining_budget() -> None:
    clock = [0.0]
    h = make_harness(Settings(progressive_after_s=5), clock=lambda: clock[0])
    h.params.podcast_creds = ("k", "s")
    h.services.media_client_factory = FakeIndex

    def transport(url, headers, body, timeout):
        clock[0] = 7.2  # KI hat fast das ganze Budget verbraucht
        return 200, b'{"output":[{"type":"function_call","name":"search_media","arguments":"{\\"query\\": \\"krimi\\"}"}]}'

    from superkugel.conversation.llm import OpenAIClient

    h.services.llm_factory = lambda key: OpenAIClient(key, "m", transport=transport, clock=lambda: clock[0])
    r = h.send(chat("ChatWasIntent", "gibt's zum hören"))
    assert "zu lang gedauert" in speech(r)


def test_search_with_only_search_call_is_counted() -> None:
    h = make_harness(Settings(progressive_after_s=5))
    h.openai.replies.append((200, {"status": "incomplete", "output": [{"type": "web_search_call", "action": {}}],
                                   "usage": {"input_tokens": 2000, "output_tokens": 0}}))
    h.send(chat("ChatWerIntent", "hat gewonnen"))
    day = next(k for k in h.store.usage if k.startswith("DAY#"))
    assert h.store.get_usage(day).searches == 1
