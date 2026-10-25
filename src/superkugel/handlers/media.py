"""Sprachbefehle für Lieblingssendungen (RSS) und die freie Mediensuche (Podcast Index)."""

from __future__ import annotations

import re

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from superkugel.audiobooks import media
from superkugel.audiobooks.matching import normalize
from superkugel.audiobooks.media import Episode, Show
from superkugel.handlers.common import Services, end_with, keep_open, play_directive, session_attrs, slot, uid
from superkugel.services.logs import log

ORDINALS = {"erste": 1, "ersten": 1, "erstes": 1, "eins": 1, "1": 1, "zweite": 2, "zweiten": 2, "zweites": 2,
            "zwei": 2, "2": 2, "dritte": 3, "dritten": 3, "drittes": 3, "drei": 3, "3": 3}
LAST = {"letzte", "letzten", "letztes"}
_CHOICE_FILLER = {"die", "das", "den", "der", "nummer", "bitte", "spiel", "spiele", "mir", "mal", "nimm", "ich",
                  "will", "möchte", "gern", "gerne", "hören", "folge"}
ORDINAL_SPOKEN = ("die erste", "die zweite", "die dritte")


def _shows(services: Services) -> list[Show]:
    try:
        return media.list_shows(services.store)
    except Exception as exc:  # noqa: BLE001
        log("shows_unavailable", error=type(exc).__name__)
        return []


def _start_episode(services: Services, hi: HandlerInput, show_name: str, genres: list[str], ep: Episode,
                   source_id: str, intro: str) -> Response:
    book = media.episode_book(show_name, genres, ep, source_id)
    media.remember_episode(services.store, book)
    cmd = services.audio().start_or_resume(uid(hi), book)
    return (hi.response_builder.speak(services.say(intro)).add_directive(play_directive(cmd))
            .set_should_end_session(True).response)


def play_show(services: Services, hi: HandlerInput, show: Show, newest: bool = False) -> Response:
    """Angefangene Folge fortsetzen – außer sie will ausdrücklich die neueste."""
    if not show.episodes:
        return end_with(services, hi, services.t("show_no_episodes", name=show.name))
    if not newest:
        progress = services.audio().progress_map(uid(hi))
        for ep in show.episodes:
            p = progress.get(f"pod-{show.show_id}-{ep.ep_id}")
            if p and p.started and not p.finished:
                return _start_episode(services, hi, show.name, show.genres, ep, show.show_id,
                                      services.t("show_resume", name=show.name, title=ep.title))
    ep = show.episodes[0]
    return _start_episode(services, hi, show.name, show.genres, ep, show.show_id,
                          services.t("show_latest", name=show.name, title=ep.title))


def play_show_intent(services: Services, hi: HandlerInput) -> Response:
    raw = slot(hi, "show")
    show = media.match_show(raw, _shows(services)) if raw else None
    if show:
        # PlayShowIntent = „spiel die neueste Folge von …“; „spiel <Sendung>“ (ohne „neu“) läuft über
        # PlayAudiobookIntent und setzt eine angefangene Folge fort.
        return play_show(services, hi, show, newest=True)
    if raw.strip():
        return search_media(services, hi, raw)  # nicht in der Liste → in den Mediatheken suchen
    return keep_open(services, hi, services.t("which_show"), services.t("which_show"))


def list_shows(services: Services, hi: HandlerInput) -> Response:
    shows = _shows(services)
    if not shows:
        key = "no_shows" if services.params.podcast_index_credentials() else "no_shows_nosearch"
        return keep_open(services, hi, services.t(key), None)
    names = [s.name for s in shows[:5]]
    listing = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " und " + names[-1]
    return keep_open(services, hi, services.t("you_have_shows", listing=listing), None)


def search_media_intent(services: Services, hi: HandlerInput, started: float | None = None) -> Response:
    deadline = started + services.settings.request_deadline_s if started is not None else None
    return search_media(services, hi, slot(hi, "query"), deadline=deadline)


def _privacy_filter(services: Services, query: str) -> str:
    """Vornamen nie an den Suchkatalog schicken."""
    name = services.settings.user_name.strip()
    if name:
        query = re.sub(rf"\b{re.escape(name)}\b", " ", query, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", query).strip()


def _budget(services: Services, deadline: float | None, need: float) -> float | None:
    """Verbleibende Zeit für einen Netzaufruf; None = reicht nicht mehr (Alexa wartet nur ca. 8 s)."""
    if deadline is None:
        return 3.0
    left = deadline - services.clock() - 0.5
    return min(3.0, left) if left >= need else None


def search_media(services: Services, hi: HandlerInput, query: str, deadline: float | None = None) -> Response:
    query = _privacy_filter(services, (query or "")[:100])
    if not query:
        return keep_open(services, hi, services.t("search_what"), services.t("search_what"))
    creds = services.params.podcast_index_credentials()
    if not creds:
        return keep_open(services, hi, services.t("search_unavailable"), None)
    if services.usage.media_searches_left() <= 0:
        log("media_search_limit_reached")
        return keep_open(services, hi, services.t("search_limit"), None)
    timeout = _budget(services, deadline, need=1.0)
    if timeout is None:
        return keep_open(services, hi, services.t("search_later", query=query), None)
    client = (services.media_client_factory or media.PodcastIndex)(*creds)
    services.usage.record_media_search()
    try:
        hits = client.search(query, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        log("media_search_failed", error=type(exc).__name__)
        return keep_open(services, hi, services.t("search_failed"), None)
    log("media_search", hits=len(hits))
    if not hits:
        return keep_open(services, hi, services.t("search_none"), None)
    attrs = session_attrs(hi)
    attrs["pending"] = "choose_media"
    attrs["media_hits"] = [{"feed_id": h.feed_id, "name": h.name} for h in hits]
    spoken = "; ".join(f"{n}: {h.name}" for n, h in zip(ORDINAL_SPOKEN, hits, strict=False))
    return keep_open(services, hi, services.t("search_results", results=spoken), services.t("search_choose"))


def _choice_index(choice: str, hits: list[dict]) -> int | None:
    """Nur echte Auswahlsätze („die zweite“, „Nummer 3“, „die letzte“) – keine Titel mit Zahlwörtern."""
    words = [w for w in normalize(choice).split() if w not in _CHOICE_FILLER]
    if len(words) == 1:
        w = words[0]
        if w in LAST:
            return len(hits)
        if w in ORDINALS:
            return ORDINALS[w]
    # Teil des Namens eines Treffers (ganze Wörter, mind. 4 Buchstaben)
    phrase = " ".join(words)
    if len(phrase) >= 4:
        for i, h in enumerate(hits):
            if re.search(rf"\b{re.escape(phrase)}\b", normalize(str(h["name"]))):
                return i + 1
    return None


def choose_hit(services: Services, hi: HandlerInput, choice: str) -> Response | None:
    """Auswahl aus den Suchergebnissen. None = keine Auswahl erkannt (dann normal weiter)."""
    attrs = session_attrs(hi)
    hits = attrs.get("media_hits") or []
    if attrs.get("pending") != "choose_media" or not hits:
        return None
    idx = _choice_index(choice, hits)
    if idx is None or not 1 <= idx <= len(hits):
        return None
    hit = hits[idx - 1]
    attrs.pop("pending", None)
    attrs.pop("media_hits", None)
    creds = services.params.podcast_index_credentials()
    if not creds:
        return keep_open(services, hi, services.t("search_unavailable"), None)
    client = (services.media_client_factory or media.PodcastIndex)(*creds)
    try:
        eps = client.latest_episodes(int(hit["feed_id"]), timeout=3.0)
    except Exception as exc:  # noqa: BLE001
        log("media_episodes_failed", error=type(exc).__name__)
        return keep_open(services, hi, services.t("search_failed"), None)
    if not eps:
        return keep_open(services, hi, services.t("show_no_episodes", name=hit["name"]), None)
    ep = eps[0]
    return _start_episode(services, hi, str(hit["name"]), ["podcast"], ep, f"pi{hit['feed_id']}",
                          services.t("show_latest", name=hit["name"], title=ep.title))


def choose_intent(services: Services, hi: HandlerInput, started: float) -> Response:
    choice = slot(hi, "ordinal") or slot(hi, "number")
    resp = choose_hit(services, hi, choice)
    if resp is not None:
        return resp
    if session_attrs(hi).get("pending") == "choose_media":
        return keep_open(services, hi, services.t("search_choose"), services.t("search_choose"))
    # Keine Suche aktiv: eine einzelne Zahl o. Ä. gehört ins Gespräch
    from superkugel.handlers.conversation import handle_chat_text

    return handle_chat_text(services, hi, choice, started)
