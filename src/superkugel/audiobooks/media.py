"""Podcasts, Hörspiele und Mediatheken-Sendungen.

* **Lieblingsliste** („Sendungen“): der Admin trägt offizielle RSS-Feeds ein (ARD, ORF, Deutschlandfunk …).
  Ein stündlicher Zeitplan in AWS holt die neuesten Folgen – unabhängig vom Admin-PC.
* **Freie Suche**: über Podcast Index (offener Podcast-Katalog, kostenloser API-Schlüssel des Admins). Die Folgen
  streamt der Echo direkt beim Anbieter (HTTPS); es wird nichts kopiert.

Datenschutz: An Podcast Index geht nur der Suchbegriff, signiert mit dem Schlüssel des Admins. Der Anbieter
einer Folge sieht beim Abspielen – wie bei jeder Podcast-App – die IP-Adresse des Echo.
"""

from __future__ import annotations

import concurrent.futures as cf
import contextlib
import email.utils
import hashlib
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import IO, Any

from superkugel.audiobooks.matching import normalize
from superkugel.audiobooks.models import Book, Chapter
from superkugel.services import net
from superkugel.services.current_context import clean_text
from superkugel.services.logs import log
from superkugel.services.storage import Store

FEED_MAX_BYTES = 8 * 1024 * 1024
FEED_MAX_ITEMS = 400  # so viele Einträge lesen, um auch bei „älteste zuerst“ die neuesten zu finden
FEED_TIMEOUT_S = 4.0
MAX_EPISODES = 10
EPISODE_TTL_S = 30 * 86400  # gemerkte Folgen (für Lesezeichen/„weiter“) – nach 30 Tagen automatisch gelöscht
AUDIO_EXT = (".mp3", ".m4a", ".aac")


@dataclass
class Episode:
    ep_id: str
    title: str
    url: str
    duration_ms: int = 0
    published: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Show:
    show_id: str
    name: str
    feed_url: str
    genres: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    episodes: list[Episode] = field(default_factory=list)
    refreshed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["episodes"] = [e.to_dict() for e in self.episodes]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Show:
        return cls(show_id=str(d["show_id"]), name=str(d["name"]), feed_url=str(d["feed_url"]),
                   genres=list(d.get("genres", [])), aliases=list(d.get("aliases", [])),
                   episodes=[Episode(**e) for e in d.get("episodes", [])], refreshed_at=float(d.get("refreshed_at", 0)))


# --------------------------------------------------------------------------- RSS
def parse_duration(raw: str | None) -> int:
    """itunes:duration → Millisekunden („3600“, „59:30“, „1:02:03“)."""
    if not raw:
        return 0
    try:
        nums = [float(p) for p in raw.strip().split(":")]
    except ValueError:
        return 0
    secs = 0.0
    for n in nums:
        secs = secs * 60 + n
    return int(secs * 1000)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _plain(tag: str) -> bool:
    """Element ohne Namensraum (z. B. <title>, nicht <itunes:title>)."""
    return "}" not in tag


def parse_feed(stream: IO[bytes], limit: int = MAX_EPISODES) -> tuple[str, list[Episode]]:
    """Liest Titel und die neuesten Folgen (nur HTTPS-Audio, keine expliziten)."""
    title = ""
    episodes: list[Episode] = []
    items = 0
    try:
        for _event, el in ET.iterparse(net.LimitedXmlStream(stream, FEED_MAX_BYTES), events=("end",)):  # noqa: S314
            tag = el.tag
            if _plain(tag) and tag == "title" and not title and el.text:
                title = clean_text(el.text, 120)  # erster <title> = Kanal (steht vor den Einträgen)
            if _local(tag) != "item":
                continue
            items += 1
            ep = _episode_from_item(el)
            el.clear()
            if ep:
                episodes.append(ep)
            if items >= FEED_MAX_ITEMS:
                break
    except ET.ParseError:
        if not title and not episodes:
            raise
        log("feed_truncated")  # Feed größer als das Limit oder fehlerhaft: bis dahin Gelesenes verwenden
    episodes.sort(key=lambda e: e.published, reverse=True)
    return title, episodes[:limit]


def _episode_from_item(item: ET.Element) -> Episode | None:
    fields: dict[str, Any] = {}
    for child in item:
        tag, local = child.tag, _local(child.tag)
        if local == "title" and child.text and (_plain(tag) or "title" not in fields):
            fields["title"] = clean_text(child.text, 140)
        elif local == "enclosure" or (local == "content" and "media" in tag.lower() and "url" not in fields):
            url = child.get("url", "")
            kind = child.get("type", "")
            if url.startswith("https://") and (kind.startswith("audio") or url.lower().split("?")[0].endswith(AUDIO_EXT)):
                fields["url"] = url
        elif local == "guid" and child.text:
            fields["guid"] = child.text.strip()
        elif local == "duration":
            fields["duration_ms"] = parse_duration(child.text)
        elif local == "explicit" and (child.text or "").strip().lower() in ("yes", "true", "explicit"):
            return None  # Folgen mit „explicit“-Kennzeichnung nie abspielen
        elif local == "pubDate" and child.text:
            with contextlib.suppress(TypeError, ValueError):
                fields["published"] = email.utils.parsedate_to_datetime(child.text.strip()).timestamp()
    if not fields.get("url") or not fields.get("title"):
        return None  # ohne HTTPS-Audio nicht abspielbar (Alexa verlangt HTTPS)
    ep_id = hashlib.sha256((fields.get("guid") or fields["url"]).encode()).hexdigest()[:12]
    return Episode(ep_id=ep_id, title=fields["title"], url=fields["url"],
                   duration_ms=int(fields.get("duration_ms", 0)), published=float(fields.get("published", 0)))


def fetch_feed(url: str) -> tuple[str, list[Episode]]:
    with net.open_url(url, FEED_TIMEOUT_S) as resp:
        return parse_feed(resp)


# --------------------------------------------------------------------------- Lieblingsliste
def slug(text: str) -> str:
    s = normalize(text).replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "sendung"


def list_shows(store: Store) -> list[Show]:
    return [Show.from_dict(d) for d in store.query_items("PODCASTS", "SHOW#")]


def save_show(store: Store, show: Show) -> None:
    store.put_item("PODCASTS", f"SHOW#{show.show_id}", show.to_dict())


def refresh_shows(store: Store, fetch: Callable[[str], tuple[str, list[Episode]]] = fetch_feed,
                  clock: Callable[[], float] = time.time) -> int:
    shows = list_shows(store)
    if not shows:
        return 0
    errors = 0
    # Jeder Abruf hat ein eigenes Socket-Timeout (FEED_TIMEOUT_S); die Lambda läuft max. 30 s.
    with cf.ThreadPoolExecutor(max_workers=min(8, len(shows))) as pool:
        futures = {pool.submit(fetch, s.feed_url): s for s in shows}
        for fut, show in futures.items():
            try:
                _title, eps = fut.result()
            except Exception as exc:  # noqa: BLE001 - ein kaputter Feed darf die anderen nicht aufhalten
                errors += 1
                log("feed_refresh_failed", error=type(exc).__name__)
                continue
            if eps:
                show.episodes, show.refreshed_at = eps, clock()
                save_show(store, show)
    return errors


_FILLER = re.compile(r"\b(die|der|das|den|dem|neueste|neuesten|neue|neuen|letzte|folge|folgen|von|vom|podcast|"
                     r"sendung|hörspiel|spiel|spiele|mir|mal|bitte|meine|meinen|mein)\b")


def _words(text: str) -> list[str]:
    return [w for w in re.sub(r"[^\w ]", " ", _FILLER.sub(" ", normalize(text))).split() if w]


def match_show(query: str, shows: list[Show], threshold: float = 0.6) -> Show | None:
    """Sendung erkennen – nur über ganze Wörter (kein „im“ → „Radiokrimi“)."""
    q = _words(query)
    if not q:
        return None
    qs = " ".join(q)
    best, best_score = None, 0.0
    for s in shows:
        for cand in [s.name, *s.aliases]:
            c = _words(cand)
            if not c:
                continue
            cs = " ".join(c)
            overlap = len(set(q) & set(c)) / max(len(set(q)), len(set(c)))
            score = max(SequenceMatcher(None, qs, cs).ratio(), overlap)
            if score > best_score:
                best, best_score = s, score
    return best if best_score >= threshold else None


# --------------------------------------------------------------------------- Folgen als abspielbare „Bücher“
def episode_book(show_name: str, genres: list[str], ep: Episode, source_id: str) -> Book:
    return Book(
        book_id=f"pod-{source_id}-{ep.ep_id}",
        title=ep.title, author=show_name, genres=tuple(genres) or ("podcast",),
        chapters=(Chapter(index=0, title=ep.title, s3_key="", duration_ms=ep.duration_ms, sha256="", url=ep.url),),
        source="podcast",
    )


def remember_episode(store: Store, book: Book) -> None:
    """Folge merken, damit AudioPlayer-Ereignisse und „weiter“ sie wiederfinden (automatisch gelöscht nach 30 Tagen)."""
    store.put_item("EPISODES", f"EP#{book.book_id}", book.to_dict(), ttl_s=EPISODE_TTL_S)


# --------------------------------------------------------------------------- Freie Suche (Podcast Index)
@dataclass
class SearchHit:
    feed_id: int
    name: str
    author: str


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes")


class PodcastIndex:
    BASE = "https://api.podcastindex.org/api/1.0"

    def __init__(self, key: str, secret: str, opener: Callable[[str, dict[str, str], float], bytes] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.key, self.secret, self.clock = key, secret, clock
        self.opener = opener or (lambda url, headers, timeout: net.get_bytes(url, timeout, 2 * 1024 * 1024, headers))

    def _get(self, path: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        now = str(int(self.clock()))
        auth = hashlib.sha1((self.key + self.secret + now).encode()).hexdigest()  # noqa: S324 - vom Anbieter vorgegeben
        url = f"{self.BASE}{path}?{urllib.parse.urlencode(params)}"
        data: dict[str, Any] = json.loads(self.opener(url, {"X-Auth-Key": self.key, "X-Auth-Date": now,
                                                            "Authorization": auth}, timeout))
        return data

    def search(self, term: str, limit: int = 3, timeout: float = 3.0) -> list[SearchHit]:
        data = self._get("/search/byterm", {"q": term[:100], "max": 15, "clean": "true"}, timeout)
        hits = []
        for f in data.get("feeds") or []:
            lang = str(f.get("language") or "").lower()
            if (lang and not lang.startswith("de")) or _truthy(f.get("explicit")):
                continue  # deutschsprachig, nicht explizit
            hits.append(SearchHit(int(f["id"]), clean_text(str(f.get("title", "")), 80), clean_text(str(f.get("author", "")), 60)))
            if len(hits) >= limit:
                break
        return hits

    def latest_episodes(self, feed_id: int, limit: int = 5, timeout: float = 3.0) -> list[Episode]:
        data = self._get("/episodes/byfeedid", {"id": feed_id, "max": limit * 2}, timeout)
        eps = []
        for it in data.get("items") or []:
            url = str(it.get("enclosureUrl") or "")
            if not url.startswith("https://") or _truthy(it.get("explicit")):
                continue
            eps.append(Episode(ep_id=str(it.get("id")), title=clean_text(str(it.get("title", "")), 140), url=url,
                               duration_ms=int(it.get("duration") or 0) * 1000, published=float(it.get("datePublished") or 0)))
        eps.sort(key=lambda e: e.published, reverse=True)
        return eps[:limit]


def iter_shows_prompt(shows: list[Show], limit: int = 15) -> Iterator[str]:
    for s in shows[:limit]:
        latest = s.episodes[0].title if s.episodes else "noch keine Folgen geladen"
        yield f"- show_id={s.show_id}: {s.name} ({', '.join(s.genres) or 'Sendung'}; neueste Folge: {latest})"
