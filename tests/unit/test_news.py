"""Nachrichten-Vorrat: Auswahl, Mischung, nichts doppelt (erfundene Meldungen)."""

from __future__ import annotations

from superkugel.services import current_context, news
from superkugel.services.storage import MemoryStore

NOW = 1_800_000_000.0

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
<item><title>Parlament beschliesst Budget</title><link>https://orf.at/stories/1/</link>
<dc:subject>Inland</dc:subject><dc:date>2027-01-15T08:00:00+01:00</dc:date></item>
</rdf:RDF>"""
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Mehr Geld fuer Pflegeheime</title><link>https://kaernten.orf.at/stories/2/</link>
<description>Die Heime bekommen mehr Mittel. Der Beschluss fiel gestern. Weiteres folgt.</description>
<category>Politik Inland</category><pubDate>Fri, 15 Jan 2027 08:00:00 +0000</pubDate></item>
</channel></rss>"""


def item(n: int, regional: bool = False, subject: str = "Inland", title: str = "", desc: str = "",
         at: float = NOW) -> dict:
    return {"id": f"i{n}", "t": title or f"Meldung {n}", "d": desc, "s": subject, "r": regional, "at": at}


def test_parses_both_feed_formats() -> None:
    a = news.parse_items(RDF, False)[0]
    assert (a["t"], a["s"], a["r"], a["d"]) == ("Parlament beschliesst Budget", "Inland", False, "")
    assert a["at"] > 0 and a["id"]
    b = news.parse_items(RSS, True)[0]
    assert (b["s"], b["r"]) == ("Politik Inland", True)
    assert b["d"] == "Die Heime bekommen mehr Mittel."


def test_pool_keeps_recent_items_replaces_duplicates_and_drops_old_ones() -> None:
    store = MemoryStore()
    news.store_pool(store, [item(1), item(2, at=NOW - 3600)], NOW)
    news.store_pool(store, [item(1, title="Neu"), item(3)], NOW + 7200)
    assert {i["id"]: i["t"] for i in news.load_pool(store)} == {"i1": "Neu", "i2": "Meldung 2", "i3": "Meldung 3"}
    news.store_pool(store, [item(9, at=NOW + 90 * 3600)], NOW + 90 * 3600)
    assert [i["id"] for i in news.load_pool(store)] == ["i9"]


def test_regional_and_interests_come_first() -> None:
    pool = [item(1), item(2, True), item(3, title="Neues Stück im Theater", subject="Kultur")]
    got = news.select(pool, set(), "", ("theater",), NOW)
    assert got[0]["id"] == "i3" and got[1]["id"] == "i2"


def test_exciting_news_is_only_an_addition() -> None:
    pool = [item(n, subject="Chronik") for n in range(5)] + [item(10, True), item(11, subject="Wirtschaft")]
    got = news.select(pool, set(), "", (), NOW)
    assert sum(1 for i in got if i["s"] == "Chronik") == 1 and len(got) == 3


def test_already_told_news_does_not_come_again() -> None:
    pool = [item(n) for n in range(6)]
    first = news.select(pool, set(), "", (), NOW)
    told = {i["id"] for i in first}
    second = news.select(pool, told, "", (), NOW)
    assert not told & {i["id"] for i in second} and len(second) == 3
    assert news.select(pool, {i["id"] for i in pool}, "", (), NOW) == []


def test_wish_filters_by_place_topic_or_region() -> None:
    pool = [item(1, True, title="Wahl in Bergdorf"), item(2, title="Sturm in Seeort"),
            item(3, subject="Kultur", title="Ausstellung"), item(4, True, title="Baustelle")]
    assert [i["id"] for i in news.select(pool, set(), "Bergdorf", (), NOW)] == ["i1"]
    assert [i["id"] for i in news.select(pool, set(), "Kultur", (), NOW)] == ["i3"]
    assert news.select(pool, set(), "Unbekanntort", (), NOW) == []
    got = {i["id"] for i in news.select(pool, set(), "Kärnten", (), NOW, region="Kärnten")}
    assert got == {"i1", "i4"}


def test_general_words_are_no_wish() -> None:
    pool = [item(1), item(2)]
    assert len(news.select(pool, set(), "Neuigkeiten aus Österreich", (), NOW)) == 2


def test_spoken_uses_title_and_short_text() -> None:
    assert news.spoken([item(1, desc="Es wird gebaut."), item(2)]) == "Meldung 1. Es wird gebaut. Meldung 2."


def test_refresh_fills_the_pool_and_keeps_the_morning_headlines() -> None:
    store = MemoryStore()

    def fetch(url: str) -> bytes:
        return RSS if "kaernten" in url else RDF

    from superkugel.config import Settings

    current_context.refresh(store, Settings(user_region="Kärnten"), fetch, clock=lambda: NOW)
    assert {i["r"] for i in news.load_pool(store)} == {True, False}
    assert store.get_item("CONTEXT", "CURRENT")["news"]["value"] == ["Parlament beschliesst Budget"]


def test_broken_feed_does_not_stop_the_refresh() -> None:
    store = MemoryStore()

    def fetch(url: str) -> bytes:
        return b"kaputt"

    from superkugel.config import Settings

    current_context.refresh(store, Settings(user_region="Kärnten"), fetch, clock=lambda: NOW)
    assert news.load_pool(store) == []
