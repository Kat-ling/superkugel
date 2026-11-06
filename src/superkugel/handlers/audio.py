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
    """„Alexa, weiter“: das zuletzt Gehörte – Hörbuch oder Sendung."""
    return resume_current(services, hi, include_podcasts=True)


def play_title(services: Services, hi: HandlerInput, started: float | None = None) -> Response:
    return play_raw(services, hi, slot(hi, "title") or "", started)


def play_raw(services: Services, hi: HandlerInput, raw: str, started: float | None = None) -> Response:
    """„Spiel …“ mit freiem Titel: Suchtreffer-Auswahl, Radio-Hinweis, Hörbuch, Sendung oder KI-Rückfall."""
    from superkugel.audiobooks import media
    from superkugel.handlers import media as media_handlers

    chosen = media_handlers.choose_hit(services, hi, raw)  # „spiel die erste“ nach einer Suche
    if chosen is not None:
        return chosen
    wish = matching.restart_wish(raw)
    if wish is not None:
        return restart(services, hi, wish)
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
    from superkugel.handlers import alexa_hints

    # „Spiel Ö1“ landet oft hier statt bei PlayRadioIntent – Radio macht Alexa. Erst nach Buch und Sendung prüfen
    # („ARD Radio Tatort“ ist eine Sendung).
    if book is None and alexa_hints.is_radio(raw):
        return alexa_hints.radio(services, hi)
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


def _jump(services: Services, hi: HandlerInput, direction: int) -> Response:
    """„Zehn Minuten zurück“: Geht es nicht so weit, läuft das Buch an derselben Stelle weiter."""
    seconds = player.duration_seconds(slot(hi, "duration"))
    if seconds <= 0:
        return keep_open(services, hi, services.t("jump_unclear"), services.t("jump_unclear"))
    token, offset = audio_context(hi)
    found = services.audio().position_from_context(uid(hi), token, offset)
    if not found:
        return keep_open(services, hi, services.t("nothing_to_resume"), services.t("which_book"))
    book, pos = found
    target = player.jump(book, pos, direction * seconds)
    if target is None:
        return _play(services, hi, book, pos, intro=services.t("jump_past_end"))
    return _play(services, hi, book, target)


def jump_back(services: Services, hi: HandlerInput) -> Response:
    return _jump(services, hi, -1)


def jump_forward(services: Services, hi: HandlerInput) -> Response:
    return _jump(services, hi, 1)


def _restart_target(services: Services, hi: HandlerInput, wish: str) -> Book | None:
    audio = services.audio()
    books = audio.books()
    if wish and books and matching.names_title(wish):
        book = matching.best_match(wish, books)[0]
        if book:
            return book
    token, offset = audio_context(hi)
    found = audio.position_from_context(uid(hi), token, offset)
    if found:
        return found[0]
    last = audio.book(str(services.store.get_state(uid(hi)).get("book_id") or ""))  # auch ein fertig gehörtes Buch
    return last or (books[0] if len(books) == 1 else None)


def _play_from_start(services: Services, hi: HandlerInput, book: Book) -> Response:
    return _play(services, hi, book, Position(0, 0), intro=services.t("restart_go", title=book.title))


def restart(services: Services, hi: HandlerInput, wish: str = "") -> Response:
    """Das ganze Buch von vorne. Geht dabei eine Hörstelle verloren, fragt die Superkugel zuerst."""
    book = _restart_target(services, hi, wish)
    if book is None:
        if not services.audio().books():
            return end_with(services, hi, services.t("no_books"))
        return keep_open(services, hi, services.t("nothing_to_resume"), services.t("which_book"))
    p = services.store.get_progress(uid(hi), book.book_id)
    if not p or not p.started or p.finished:
        return _play_from_start(services, hi, book)
    attrs = session_attrs(hi)
    attrs["pending"], attrs["restart_book_id"] = "restart_book", book.book_id
    question = services.t("restart_ask", title=book.title)
    return keep_open(services, hi, question, question)


def restart_intent(services: Services, hi: HandlerInput) -> Response:
    return restart(services, hi)


def restart_yes(services: Services, hi: HandlerInput) -> Response:
    book = services.audio().book(str(session_attrs(hi).pop("restart_book_id", "")))
    if book is None:
        return keep_open(services, hi, services.t("nothing_to_resume"), services.t("which_book"))
    return _play_from_start(services, hi, book)


def restart_no(services: Services, hi: HandlerInput) -> Response:
    session_attrs(hi).pop("restart_book_id", None)
    return end_with(services, hi, services.t("restart_declined"))


def restart_answer(services: Services, hi: HandlerInput, text: str) -> Response | None:
    """Antwort auf die Rückfrage in einem längeren Satz („ja bitte“, „lieber nicht“). None: Es war keine Antwort."""
    first = (text.lower().split() or [""])[0]
    if first in ("ja", "gern", "gerne", "genau", "bitte"):
        session_attrs(hi).pop("pending", None)
        return restart_yes(services, hi)
    if first in ("nein", "lieber", "nicht"):
        session_attrs(hi).pop("pending", None)
        return restart_no(services, hi)
    return None


def next_chapter(services: Services, hi: HandlerInput) -> Response:
    return _seek(services, hi, "next")


def previous(services: Services, hi: HandlerInput) -> Response:
    """AMAZON.PreviousIntent („Alexa, zurück“): ein Stück zurück – für Hörbücher hilfreicher als ein ganzes Kapitel."""
    return _seek(services, hi, "rewind")


def previous_chapter(services: Services, hi: HandlerInput) -> Response:
    return _seek(services, hi, "previous")


def start_over(services: Services, hi: HandlerInput) -> Response:
    return _seek(services, hi, "startover")


def whats_playing(services: Services, hi: HandlerInput) -> Response:
    token, offset = audio_context(hi)
    found = services.audio().position_from_context(uid(hi), token, offset)
    if not found:
        return end_with(services, hi, services.t("nothing_playing"))
    book, pos = found
    by = f" von {book.author}" if book.author else ""
    return end_with(services, hi, f"Das ist {book.title}{by}, Kapitel {pos.chapter + 1} von {len(book.chapters)}.")


def unsupported(services: Services, hi: HandlerInput) -> Response:
    return end_with(services, hi, services.t("unsupported"))
