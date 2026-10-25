from __future__ import annotations

import json

import pytest

from conftest import FakeOpenAI, book
from superkugel.audiobooks.models import Progress
from superkugel.conversation.carriers import CARRIERS, INTENT_TO_CARRIER, chat_intent_name, reconstruct
from superkugel.conversation.history import History
from superkugel.conversation.llm import LlmError, OpenAIClient, parse_response
from superkugel.conversation.prompt import BASE_PROMPT, build_instructions, library_block
from superkugel.speech.styles import get_style


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


# --- Gesprächskontext ----------------------------------------------------
def test_history_keeps_latest_turns_and_starts_with_user() -> None:
    h = History()
    for i in range(12):
        h.add("user", f"frage {i}")
        h.add("assistant", f"antwort {i}")
    t = h.trimmed(max_turns=3, max_chars=10_000)
    assert len(t.turns) == 6
    assert t.turns[0] == {"role": "user", "content": "frage 9"}


def test_history_char_limit_drops_oldest() -> None:
    h = History()
    h.add("user", "a" * 500)
    h.add("assistant", "b" * 500)
    h.add("user", "c" * 100)
    h.add("assistant", "d" * 100)
    t = h.trimmed(max_turns=10, max_chars=400)
    assert [x["content"][0] for x in t.turns] == ["c", "d"]


def test_history_from_attributes_rejects_garbage() -> None:
    h = History.from_attributes([{"role": "system", "content": "böse"}, {"role": "user", "content": "hi"}, "x", None])
    assert h.turns == [{"role": "user", "content": "hi"}]
    assert History.from_attributes("kaputt").turns == []


def test_follow_up_question_is_sent_with_context() -> None:
    fake = FakeOpenAI().text("Inflation heißt ...").text("Weil das Geld weniger wert ist.")
    client = OpenAIClient("k", "m", transport=fake)
    h = History()
    r1 = client.complete("sys", h.as_input("was bedeutet eigentlich inflation"), deadline=1e12)
    h.add("user", "was bedeutet eigentlich inflation")
    h.add("assistant", r1.text)
    client.complete("sys", h.as_input("und warum wird dann alles teurer"), deadline=1e12)
    sent = fake.requests[1]["body"]["input"]
    assert [m["content"] for m in sent] == ["was bedeutet eigentlich inflation", "Inflation heißt ...",
                                            "und warum wird dann alles teurer"]


# --- Trägerwörter --------------------------------------------------------
def test_carriers_are_unique_and_reconstruct() -> None:
    names = [chat_intent_name(c) for c in CARRIERS]
    assert len(names) == len(set(names))
    assert reconstruct("ChatWarumIntent", "wird alles teurer") == "warum wird alles teurer"
    assert reconstruct("ChatWieVielIntent", "kostet butter") == "wie viel kostet butter"
    assert reconstruct("ChatGruessGottIntent", "wie geht's") == "grüß gott wie geht's"
    assert INTENT_TO_CARRIER["ChatNeinIntent"] == "nein"


# --- Prompt --------------------------------------------------------------
def test_prompt_contains_style_library_and_honesty() -> None:
    b = book()
    text = build_instructions(get_style("kaernten"), [b], {b.book_id: Progress(b.book_id, chapter=1, started=True)},
                              address="du")
    assert "Kärntner" in text and "book_id=mord-im-kraeuterbeet" in text
    assert "Kapitel 2 von 3" in text and "duzt" in text
    assert "kein Mensch" in BASE_PROMPT and "Erfinde nie Titel" in BASE_PROMPT
    assert len(BASE_PROMPT) < 4000  # kurz halten wegen Latenz


def test_library_block_empty() -> None:
    assert "(noch keine)" in library_block([], {})


@pytest.mark.parametrize("style", ["kaernten", "bayern", "standard", "unbekannt"])
def test_styles_have_both_address_forms(style: str) -> None:
    s = get_style(style)
    assert s.greeting["du"] and s.greeting["sie"] and s.goodbye["du"] and s.goodbye["sie"]


# --- OpenAI-Client -------------------------------------------------------
def test_payload_uses_responses_api_without_storage() -> None:
    fake = FakeOpenAI().text("Hallo")
    OpenAIClient("sk", "gpt-6-luna", transport=fake, max_output_tokens=200).complete("sys", [], deadline=1e12)
    req = fake.requests[0]
    assert req["url"].endswith("/responses")
    assert req["body"]["store"] is False and req["body"]["max_output_tokens"] == 200
    assert req["body"]["reasoning"] == {"effort": "none"}
    assert req["headers"]["Authorization"] == "Bearer sk"


def test_retry_once_on_server_error() -> None:
    fake = FakeOpenAI().status(503).text("ok")
    reply = OpenAIClient("k", "m", transport=fake).complete("s", [], deadline=1e12)
    assert reply.text == "ok" and len(fake.requests) == 2


@pytest.mark.parametrize(("code", "body", "kind"), [(401, b"{}", "auth"), (400, b"{}", "bad_request"),
                                                    (429, b'{"error":{"code":"insufficient_quota"}}', "quota")])
def test_non_retryable_errors(code: int, body: bytes, kind: str) -> None:
    fake = FakeOpenAI().status(code, body).text("nie")
    with pytest.raises(LlmError) as e:
        OpenAIClient("k", "m", transport=fake).complete("s", [], deadline=1e12)
    assert e.value.kind == kind and len(fake.requests) == 1


def test_no_retry_when_deadline_too_close() -> None:
    clock = Clock()
    fake = FakeOpenAI().error("timeout").text("zu spät")

    def slow(url, headers, body, timeout):
        clock.t += 4.0  # der erste Versuch verbraucht 4 s
        return fake(url, headers, body, timeout)

    with pytest.raises(LlmError) as e:
        OpenAIClient("k", "m", transport=slow, clock=clock).complete("s", [], deadline=clock.t + 5.5)
    assert e.value.kind == "timeout" and len(fake.requests) == 1


def test_timeout_passed_as_remaining_budget() -> None:
    clock = Clock()
    fake = FakeOpenAI().text("x")
    OpenAIClient("k", "m", transport=fake, clock=clock).complete("s", [], deadline=clock.t + 4.0)
    assert fake.requests[0]["timeout"] == pytest.approx(4.0)


def test_parse_tool_call_and_truncation() -> None:
    r = parse_response({"status": "incomplete", "output": [
        {"type": "function_call", "name": "play_audiobook", "arguments": json.dumps({"book_id": "x"})}],
        "usage": {"input_tokens": 10, "output_tokens": 2, "input_tokens_details": {"cached_tokens": 4}}})
    assert r.tool_calls[0].arguments == {"book_id": "x"} and r.truncated
    assert r.usage.cached_input_tokens == 4


def test_parse_empty_response_is_error() -> None:
    with pytest.raises(LlmError):
        parse_response({"output": []})
