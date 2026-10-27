"""Hörbuch-Sprachbefehle (innerhalb und außerhalb einer Skill-Sitzung)."""

from __future__ import annotations

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.interfaces.audioplayer import StopDirective

from superkugel.audiobooks import matching, player
from superkugel.audiobooks.models import Book
from superkugel.audiobooks.player import Position
from superkugel.handlers.common import (
    Services,
    audio_context,
    end_with,
    keep_open,
    play_directive,
    session_attrs,
    slot,
    uid,
)
from superkugel.services.logs import log
from superkugel.services.ops import Mode


def _play(services: Services, hi: HandlerInput, book: Book, pos: Position | None = None,
          intro: str | None = None) -> Response:
    audio = services.audio()
    cmd = audio.start_or_resume(uid(hi), book) if pos is None else audio.command(uid(hi), book, pos)
    if pos is None:
        services.count("audiobook")
    rb = hi.response_builder.add_directive(play_directive(cmd)).set_should_end_session(True)
    if intro:
        rb.speak(services.say(intro))
    return rb.response


def _intro(book: Book, chapter: int, resumed: bool) -> str:
    if book.source == "podcast":
        return f"Gern, es geht weiter mit {book.author}: {book.title}." if resumed else f"Gern, {book.title}."
    if resumed:
        return f"Gern, es geht weiter mit {book.title}, Kapitel {chapter + 1}."
    return f"Gern. {book.title}" + (f" von {book.author}." if book.author else ".")


def resume_current(services: Services, hi: HandlerInput, include_podcasts: bool = False) -> Response:
    if services.params.mode() is Mode.MAINTENANCE:
        return end_with(services, hi, services.t("books_paused"))
    audio = services.audio()
    user = uid(hi)
    cur = audio.current_book(user, include_podcasts=include_podcasts)
    if not cur:
        if not audio.books():
            return end_with(services, hi, services.t("no_books"))
        return keep_open(services, hi, services.t("nothing_to_resume"), services.t("which_book"))
    book, p = cur
    return _play(services, hi, book, intro=_intro(book, p.chapter, resumed=p.started))


def resume_any(services: Services, hi: HandlerInput) -> Response:
    """„Alexa, weiter“: das zuletzt Gehörte – Hörbuch, Sendung oder Radio (Radio startet live neu)."""
    from superkugel.handlers import radio

    station = radio.current(services, hi)
    if station is None:
        last = radio.last_played(services, hi)
        if last:
            try:
                newest = max((p.updated_at for p in services.audio().progress_map(uid(hi)).values()), default=0.0)
            except Exception:  # noqa: BLE001
                newest = 0.0
            station = last[0] if last[1] > newest else None
    if station is not None:
        return radio.play(services, hi, station)
    return resume_current(services, hi, include_podcasts=True)


def play_title(services: Services, hi: HandlerInput, started: float | None = None) -> Response:
    return play_raw(services, hi, slot(hi, "title") or "", started)


def play_raw(services: Services, hi: HandlerInput, raw: str, started: float | None = None) -> Response:
    """„Spiel …“ mit freiem Titel: Suchtreffer-Auswahl, Radiosender, Hörbuch, Sendung oder KI-Rückfall."""
    from superkugel.audiobooks import media
    from superkugel.handlers import media as media_handlers

    chosen = media_handlers.choose_hit(services, hi, raw)  # „spiel die erste“ nach einer Suche
    if chosen is not None:
        return chosen
    from superkugel.handlers import radio
    from superkugel.radio import stations

    station = stations.match(raw, services.settings)  # „Spiel Ö1“ landet oft hier statt bei PlayRadioIntent
    if station:
        return radio.play(services, hi, station)
    norm = matching.normalize(raw)
    if "weiter" in norm.split():
        return resume_current(services, hi)
    newest = any(w in norm.split() for w in ("neu", "neue", "neuen", "neues", "neuesten", "neuste"))
    audio = services.audio()
    books = audio.books()
    genre = matching.detect_genre(raw)
    book, candidates = matching.best_match(raw, books) if books else (None, [])
    if book is None and candidates:
        names = " oder ".join(f"{m.book.title}" for m in candidates[:2])
        return keep_open(services, hi, services.t("did_you_mean", names=names), services.t("say_title_again"))
    if book is None and (genre or newest):
        book = matching.pick_by_genre(books, genre, audio.progress_map(uid(hi)), newest=newest)
    if book is None and raw.strip():
        try:
            show = media.match_show(raw, media.list_shows(services.store))
        except Exception:  # noqa: BLE001
            show = None
        if show:
            return media_handlers.play_show(services, hi, show)
    if book is None and not books:
        return end_with(services, hi, services.t("no_books"))
    if book is None and raw.strip() and services.params.mode() is Mode.NORMAL:
        # Kein Treffer im Titel/Autor (z. B. „Sherlock Holmes“, „die Lady Detectives“): die KI darf aus der
        # vorhandenen Bibliothek wählen (nur bekannte book_ids werden abgespielt) oder ehrlich verneinen.
        from superkugel.handlers.conversation import handle_chat_text

        return handle_chat_text(services, hi, f"Spiel {raw}", started if started is not None else services.clock())
    if book is None:
        return keep_open(services, hi, services.t("unknown_title"), services.t("which_book"))
    p = services.store.get_progress(uid(hi), book.book_id)
    resumed = bool(p and p.started and not p.finished)
    return _play(services, hi, book, intro=_intro(book, p.chapter if p else 0, resumed))


def play_genre(services: Services, hi: HandlerInput, newest: bool = False) -> Response:
    audio = services.audio()
    books = audio.books()
    if not books:
        return end_with(services, hi, services.t("no_books"))
    genre_raw = slot(hi, "genre") or ""
    genre = matching.detect_genre(genre_raw) if genre_raw else None
    progress = audio.progress_map(uid(hi))
    book = matching.pick_by_genre(books, genre, progress, newest=newest)
    if book is None:
        session_attrs(hi)["pending"] = "list_books"
        return keep_open(services, hi, services.t("no_genre"), services.t("say_list"))
    p = progress.get(book.book_id)
    resumed = bool(p and p.started and not p.finished)
    return _play(services, hi, book, intro=_intro(book, p.chapter if p else 0, resumed))


def list_books(services: Services, hi: HandlerInput) -> Response:
    audio = services.audio()
    books = audio.books()
    if not books:
        return end_with(services, hi, services.t("no_books"))
    genre_raw = slot(hi, "genre") or ""
    genre = matching.detect_genre(genre_raw) if genre_raw else None
    progress = audio.progress_map(uid(hi))
    pool = [b for b in books if genre is None or matching.book_has_genre(b, genre)]
    unheard = [b for b in pool if not (progress.get(b.book_id) and progress[b.book_id].finished)]
    if not unheard:
        return keep_open(services, hi, services.t("all_heard"), services.t("which_book"))
    unheard.sort(key=lambda b: b.imported_at, reverse=True)
    names = [b.title for b in unheard[:4]]
    listing = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " und " + names[-1]
    more = f" Und noch {len(unheard) - 4} weitere." if len(unheard) > 4 else ""
    return keep_open(services, hi, services.t("you_have", listing=listing, more=more), services.t("say_title"))


def pause(services: Services, hi: HandlerInput) -> Response:
    # Erst anhalten, dann speichern: auch bei Speicher-Ausfall muss „Pause“ wirken.
    hi.response_builder.add_directive(StopDirective()).set_should_end_session(True)
    token, offset = audio_context(hi)
    if token:
        try:
            services.audio().on_stopped(uid(hi), token, int(offset or 0))
        except Exception as exc:  # noqa: BLE001
            log("progress_save_failed", error=type(exc).__name__)
    return hi.response_builder.response


def _seek(services: Services, hi: HandlerInput, kind: str) -> Response:
    from superkugel.handlers import radio

    station = radio.current(services, hi, active_only=True)
    if station is not None:  # live: kein Spulen; „nächstes/voriges“ wechselt den Sender, „von vorn“ startet neu
        if kind in ("next", "previous", "back"):
            return radio.switch(services, hi, station, 1 if kind == "next" else -1)
        if kind == "startover":
            return radio.play(services, hi, station)
        return radio.no_seek(services, hi)
    if kind == "back":
        kind = "rewind"
    audio = services.audio()
    user = uid(hi)
    token, offset = audio_context(hi)
    found = audio.position_from_context(user, token, offset)
    if not found:
        return keep_open(services, hi, services.t("nothing_to_resume"), services.t("which_book"))
    book, pos = found
    s = services.settings
    target: Position | None
    if kind == "rewind":
        target = player.rewind(book, pos, s.rewind_s)
    elif kind == "forward":
        target = player.forward(book, pos, s.forward_s)
    elif kind == "next":
        nxt = player.next_chapter(book, pos.chapter)
        target = Position(nxt, 0) if nxt is not None else None
    elif kind == "previous":
        target = Position(player.previous_chapter(book, pos.chapter), 0)
    else:  # startover = Kapitelanfang
        target = Position(pos.chapter, 0)
    if target is None:
        return end_with(services, hi, services.t("last_chapter"))
    return _play(services, hi, book, target)


def rewind(services: Services, hi: HandlerInput) -> Response:
    return _seek(services, hi, "rewind")


def forward(services: Services, hi: HandlerInput) -> Response:
    return _seek(services, hi, "forward")


def next_chapter(services: Services, hi: HandlerInput) -> Response:
    return _seek(services, hi, "next")


def previous(services: Services, hi: HandlerInput) -> Response:
    """AMAZON.PreviousIntent („Alexa, zurück“): ein Stück zurück – für Hörbücher hilfreicher als ein ganzes Kapitel.
    Beim Radio: vorheriger Sender."""
    return _seek(services, hi, "back")


def previous_chapter(services: Services, hi: HandlerInput) -> Response:
    return _seek(services, hi, "previous")


def start_over(services: Services, hi: HandlerInput) -> Response:
    return _seek(services, hi, "startover")


def whats_playing(services: Services, hi: HandlerInput) -> Response:
    from superkugel.handlers import radio

    station = radio.current(services, hi, active_only=True)
    if station is not None:
        return radio.whats_playing(services, hi, station)
    token, offset = audio_context(hi)
    found = services.audio().position_from_context(uid(hi), token, offset)
    if not found:
        return end_with(services, hi, services.t("nothing_playing"))
    book, pos = found
    by = f" von {book.author}" if book.author else ""
    return end_with(services, hi, f"Das ist {book.title}{by}, Kapitel {pos.chapter + 1} von {len(book.chapters)}.")


def unsupported(services: Services, hi: HandlerInput) -> Response:
    return end_with(services, hi, services.t("unsupported"))
