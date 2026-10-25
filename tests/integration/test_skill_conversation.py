"""Alexa-Request → Skill → Antwort, mit gemockter OpenAI-API."""

from __future__ import annotations

import time

from conftest import attrs, book, ends_session, intent, launch, make_harness, speech
from superkugel.config import Settings
from superkugel.services.ops import Mode


def chat(text_intent: str, query: str, session: dict | None = None) -> dict:
    return intent(text_intent, {"query": query}, session=session or {})


def test_launch_greets_and_keeps_session_open(harness) -> None:
    r = harness.send(launch())
    assert "Grüß Gott" in speech(r) and ends_session(r) is False
    assert r["response"]["reprompt"]["outputSpeech"]["ssml"]


def test_launch_offers_audiobook_when_one_is_in_progress(harness) -> None:
    harness.store.put_book(book())
    from conftest import DEVICE, USER
    from superkugel.audiobooks.models import Progress
    from superkugel.handlers.common import hash_user

    harness.store.put_progress(hash_user(USER, DEVICE), Progress("mord-im-kraeuterbeet", chapter=1, started=True))
    r = harness.send(launch())
    assert "Hörbuch weiterspielen" in speech(r) and attrs(r)["pending"] == "resume_book"
    r2 = harness.send(intent("AMAZON.YesIntent", session=attrs(r)))
    assert r2["response"]["directives"][0]["type"] == "AudioPlayer.Play"


def test_question_answer_and_follow_up_context(harness) -> None:
    harness.openai.text("Inflation heißt, dass Geld an Wert verliert.").text("Weil die Preise steigen.")
    r1 = harness.send(chat("ChatWasIntent", "bedeutet eigentlich inflation"))
    assert "Inflation heißt" in speech(r1) and ends_session(r1) is False
    r2 = harness.send(chat("ChatUndIntent", "warum wird dann alles teurer", attrs(r1)))
    assert "Preise" in speech(r2)
    sent = harness.openai.requests[1]["body"]["input"]
    assert sent[0]["content"] == "was bedeutet eigentlich inflation"
    assert sent[-1]["content"] == "und warum wird dann alles teurer"
    assert len(attrs(r2)["history"]) == 4


def test_dialect_input_passed_through_unchanged(harness) -> None:
    harness.openai.text("Freilich, a bissl Jause schadet nie.")
    harness.send(chat("ChatIchIntent", "hab heut a jause gmacht"))
    assert harness.openai.requests[0]["body"]["input"][-1]["content"] == "ich hab heut a jause gmacht"


def test_repeat_last_answer_slowly(harness) -> None:
    harness.openai.text("Der Apfelstrudel braucht Zimt.")
    r1 = harness.send(chat("ChatWieIntent", "macht man apfelstrudel"))
    r2 = harness.send(intent("AMAZON.RepeatIntent", session=attrs(r1)))
    assert "Zimt" in speech(r2) and 'rate="85%"' in speech(r2)
    assert len(harness.openai.requests) == 1  # keine neue KI-Anfrage


def test_session_resume_after_relaunch(harness) -> None:
    harness.openai.text("Rosen schneidet man im Frühjahr.")
    harness.send(chat("ChatWannIntent", "schneidet man rosen"))
    r = harness.send(launch())
    assert "Da bin ich wieder" in speech(r) and len(attrs(r)["history"]) == 2


def _start_book(h) -> None:
    from conftest import DEVICE, USER
    from superkugel.audiobooks.models import Progress
    from superkugel.handlers.common import hash_user

    h.store.put_book(book())
    h.store.put_progress(hash_user(USER, DEVICE), Progress("mord-im-kraeuterbeet", started=True))


def test_goodbye_clears_resume_and_no_double_question(harness) -> None:
    harness.openai.text("Gern.").text("Gern.")
    r = harness.send(chat("ChatWannIntent", "blühen rosen"))
    harness.send(intent("AMAZON.StopIntent", session=attrs(r)))
    assert "Da bin ich wieder" not in speech(harness.send(launch()))
    _start_book(harness)
    harness.send(chat("ChatWannIntent", "blühen tulpen"))
    r = harness.send(launch())
    assert "Da bin ich wieder" in speech(r) and "Hörbuch" not in speech(r)


def test_limit_offers_audiobook_and_yes_plays() -> None:
    h = make_harness(Settings(daily_cost_limit_usd=0.0, progressive_after_s=5))
    _start_book(h)
    r = h.send(chat("ChatWasIntent", "gibt's neues"))
    assert "Feierabend" in speech(r) and ends_session(r) is False
    r = h.send(intent("AMAZON.YesIntent", session=attrs(r)))
    assert r["response"]["directives"][0]["type"] == "AudioPlayer.Play"


def test_no_genre_question_yes_lists_books(harness) -> None:
    harness.store.put_book(book())
    r = harness.send(intent("PlayGenreIntent", {"genre": "märchen"}, session={}))
    r = harness.send(intent("AMAZON.YesIntent", session=attrs(r)))
    assert "Mord im Kräuterbeet" in speech(r) and not harness.openai.requests


def test_forget_conversation(harness) -> None:
    harness.openai.text("Gern.")
    r1 = harness.send(chat("ChatIchIntent", "heiße maria"))
    r2 = harness.send(intent("ForgetConversationIntent", session=attrs(r1)))
    assert attrs(r2)["history"] == []
    assert "Da bin ich wieder" not in speech(harness.send(launch()))


def test_fallback_is_patient_and_ends_only_after_limit(harness) -> None:
    r = harness.send(intent("AMAZON.FallbackIntent", session={}))
    assert ends_session(r) is False
    for n in range(2, 5):
        r = harness.send(intent("AMAZON.FallbackIntent", session=attrs(r)))
        assert ends_session(r) is False, n
        if n % 2 == 0:
            assert "Sag mal" in speech(r)
    r = harness.send(intent("AMAZON.FallbackIntent", session=attrs(r)))
    assert ends_session(r) is True and "öffne Superkugel" in speech(r)


def test_name_and_du_form() -> None:
    h = make_harness(Settings(address_form="du", user_name="Maria", progressive_after_s=5))
    assert "Servus Maria!" in speech(h.send(launch()))
    h.openai.text("Gern.")
    h.send(chat("ChatWasIntent", "ist los"))
    instr = h.openai.requests[0]["body"]["instructions"]
    assert "duzt" in instr and "Sie heißt Maria" in instr
    r = h.send(intent("AMAZON.StopIntent", session={}))
    assert "Pfiat di, Maria" in speech(r)


def test_quick_answer_needs_no_filler() -> None:
    h = make_harness(Settings())  # Standard: Lückenfüller erst nach 4,5 s
    h.openai.text("Gleich da.")
    h.send(chat("ChatWasIntent", "ist los"))
    assert h.progressive_calls == []

def test_stop_says_goodbye_and_ends(harness) -> None:
    r = harness.send(intent("AMAZON.StopIntent", session={}))
    assert ends_session(r) is True and speech(r)


def test_llm_tool_call_starts_known_book_only(harness) -> None:
    harness.store.put_book(book())
    harness.openai.tool("mord-im-kraeuterbeet", "Gern, ich spiel deinen Gartenkrimi.")
    r = harness.send(chat("ChatHastDuIntent", "was mit garten"))
    assert r["response"]["directives"][0]["type"] == "AudioPlayer.Play" and ends_session(r) is True
    harness.openai.tool("erfundenes-buch").text("dummy")
    r = harness.send(chat("ChatHastDuIntent", "was anderes"))
    assert not r["response"].get("directives")  # erfundene ID wird nicht abgespielt


def test_library_is_in_prompt_so_model_cannot_invent(harness) -> None:
    harness.store.put_book(book())
    harness.openai.text("Du hast Mord im Kräuterbeet.")
    harness.send(chat("ChatWelcheIntent", "bücher hab ich"))
    instr = harness.openai.requests[0]["body"]["instructions"]
    assert "Mord im Kräuterbeet" in instr and harness.openai.requests[0]["body"]["tools"][0]["name"] == "play_audiobook"


def test_progressive_response_sent_when_answer_is_slow() -> None:
    h = make_harness(Settings(progressive_after_s=0.05))

    def slow(url, headers, body, timeout):
        time.sleep(0.3)
        return 200, b'{"output":[{"type":"message","content":[{"type":"output_text","text":"Fertig."}]}]}'

    h.services.llm_factory = lambda key: __import__("superkugel.conversation.llm", fromlist=["x"]).OpenAIClient(
        key, "m", transport=slow)
    r = h.send(chat("ChatWasIntent", "ist los"))
    assert "Fertig" in speech(r) and len(h.progressive_calls) == 1


def test_maintenance_mode_ends_immediately(harness) -> None:
    harness.params._mode = Mode.MAINTENANCE
    r = harness.send(launch())
    assert "Pause" in speech(r) and ends_session(r) is True
    r = harness.send(chat("ChatWasIntent", "ist das"))
    assert ends_session(r) is True and not harness.openai.requests


def test_audiobooks_only_mode_blocks_ai(harness) -> None:
    harness.params._mode = Mode.AUDIOBOOKS_ONLY
    r = harness.send(chat("ChatWasIntent", "ist das"))
    assert "Hörbücher" in speech(r) and not harness.openai.requests


def test_choice_after_launch_plaudern(harness) -> None:
    r = harness.send(intent("StartChatIntent", session={"pending": "resume_book"}))
    assert "Worüber" in speech(r) and ends_session(r) is False and "pending" not in attrs(r)
