"""Nachrichten über den Skill: Werkzeug der KI, „was noch“, nichts doppelt, Suche nur als Ersatz (erfundene Meldungen)."""

from __future__ import annotations

import datetime as dt
import json

from conftest import attrs, intent, make_harness, speech
from superkugel.config import Settings
from superkugel.services import news

NOW = dt.datetime(2027, 1, 15, 9, 0, tzinfo=dt.UTC)


def item(n: int, regional: bool = False, title: str = "", subject: str = "Inland") -> dict:
    return {"id": f"i{n}", "t": title or f"Meldung {n}", "d": "", "s": subject, "r": regional, "at": NOW.timestamp()}


def harness(items: list[dict] | None = None, **settings):
    h = make_harness(Settings(progressive_after_s=5.0, address_form="du", **settings))
    h.services.now = lambda: NOW
    news.store_pool(h.store, items if items is not None else [item(n) for n in range(7)], NOW.timestamp())
    return h


def news_call(h, ort: str = "", thema: str = "") -> None:
    h.openai.replies.append((200, {"status": "completed", "output": [
        {"type": "function_call", "name": "nachrichten", "call_id": "c1",
         "arguments": json.dumps({"ort": ort, "thema": thema})}],
        "usage": {"input_tokens": 1, "output_tokens": 1}}))


def chat(name: str, query: str, session: dict | None = None) -> dict:
    return intent(name, {"query": query}, session=session if session is not None else {})


def test_news_are_read_by_the_code_and_what_else_brings_new_ones() -> None:
    h = harness()
    news_call(h)
    r = h.send(chat("ChatWasIntent", "gibt's Neues"))
    first = speech(r)
    assert "Laut ORF" in first and first.count("Meldung") == 3
    news_call(h)
    r = h.send(chat("ChatWasIntent", "noch", attrs(r)))
    second = speech(r)
    told = [f"Meldung {n}" for n in range(7) if f"Meldung {n}" in first]
    assert second.count("Meldung") == 3 and not any(x in second for x in told)
    assert any("Meldung" in t["text"] for t in attrs(r)["history"] if "text" in t) or attrs(r)["history"]


def test_told_news_stay_told_in_a_new_session() -> None:
    h = harness([item(n) for n in range(3)])
    news_call(h)
    h.send(chat("ChatWasIntent", "gibt's Neues"))
    news_call(h)
    r = h.send(chat("ChatWasIntent", "gibt's Neues"))
    assert "Mehr Neues habe ich gerade nicht" in speech(r) and "Meldung" not in speech(r)


def test_wish_without_a_hit_uses_one_web_search() -> None:
    h = harness()
    news_call(h, ort="Bergdorf")
    h.openai.text("In Bergdorf wird der Hauptplatz neu gestaltet.")
    r = h.send(chat("ChatWasIntent", "gibt's Neues aus Bergdorf"))
    assert "Hauptplatz" in speech(r) and len(h.openai.requests) == 2
    tools = h.openai.requests[1]["body"]["tools"]
    assert [t["type"] for t in tools] == ["web_search"]


def test_wish_without_a_hit_is_honest_when_the_search_budget_is_gone() -> None:
    h = harness(web_search_enabled=False)
    news_call(h, thema="Bergdorf")
    r = h.send(chat("ChatWasIntent", "gibt's Neues aus Bergdorf"))
    assert "Dazu habe ich gerade nichts Neues" in speech(r) and len(h.openai.requests) == 1


def test_prompt_offers_the_tool_and_no_headlines() -> None:
    h = harness()
    h.store.put_item("CONTEXT", "CURRENT", {"news": {"value": ["Geheime Schlagzeile"], "at": NOW.timestamp()}})
    h.openai.text("Gut.")
    h.send(chat("ChatWieIntent", "geht es dir"))
    body = h.openai.requests[0]["body"]
    assert "Geheime Schlagzeile" not in body["instructions"]
    assert "nachrichten" in {t.get("name") for t in body["tools"]}


def test_no_news_titles_in_the_logs(capsys) -> None:
    h = harness()
    news_call(h)
    h.send(chat("ChatWasIntent", "gibt's Neues"))
    assert "Meldung" not in capsys.readouterr().out
