"""Hörbuch-Anwendungslogik: Bibliothek, Fortschritt, Wiedergabebefehle.

Liefert Alexa-unabhängige ``PlayCommand``-Objekte; die Handler übersetzen sie in Direktiven.
Alle kritischen Entscheidungen (Kapitel, Offset) sind deterministisch.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from superkugel.audiobooks import player
from superkugel.audiobooks.hosting import UrlSigner
from superkugel.audiobooks.models import Book, Progress
from superkugel.audiobooks.player import Position
from superkugel.services.logs import log, metric
from superkugel.services.storage import Store


@dataclass(frozen=True)
class PlayCommand:
    url: str
    token: str
    offset_ms: int
    behavior: str  # REPLACE_ALL | ENQUEUE
    expected_previous_token: str | None
    book: Book
    chapter: int


class AudiobookService:
    def __init__(self, store: Store, signer: UrlSigner, *, max_retries: int = 2,
                 clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.signer = signer
        self.max_retries = max_retries
        self.clock = clock
        self._books: list[Book] | None = None

    # --- Bibliothek -------------------------------------------------------
    def books(self) -> list[Book]:
        if self._books is None:
            self._books = [b for b in self.store.list_books() if b.chapters]
        return self._books

    def book(self, book_id: str) -> Book | None:
        return next((b for b in self.books() if b.book_id == book_id), None)

    def progress_map(self, uid: str) -> dict[str, Progress]:
        return {p.book_id: p for p in self.store.list_progress(uid)}

    def current_book(self, uid: str) -> tuple[Book, Progress] | None:
        """Das zuletzt gehörte, nicht beendete Buch."""
        state = self.store.get_state(uid)
        progress = self.progress_map(uid)
        candidates = []
        if state.get("book_id") in progress:
            candidates.append(progress[state["book_id"]])
        candidates += sorted((p for p in progress.values() if p.started and not p.finished),
                             key=lambda p: p.updated_at, reverse=True)
        for p in candidates:
            book = self.book(p.book_id)
            if book and not p.finished:
                return book, p
        return None

    # --- Wiedergabe -------------------------------------------------------
    def command(self, uid: str, book: Book, pos: Position, *, behavior: str = "REPLACE_ALL",
                expected_previous_token: str | None = None, persist_position: bool = True) -> PlayCommand:
        pos = player.clamp(book, pos)
        chapter = book.chapters[pos.chapter]
        token = player.make_token(book.book_id, pos.chapter)
        url = self.signer.url_for(chapter.s3_key)
        if behavior == "REPLACE_ALL":
            if persist_position:
                self._save(uid, book.book_id, pos.chapter, pos.offset_ms, started=True, reset_failures=True)
            self.store.put_state(uid, {"book_id": book.book_id, "token": token})
        return PlayCommand(url=url, token=token, offset_ms=pos.offset_ms, behavior=behavior,
                           expected_previous_token=expected_previous_token, book=book, chapter=pos.chapter)

    def start_or_resume(self, uid: str, book: Book) -> PlayCommand:
        p = self.store.get_progress(uid, book.book_id)
        if p is None or p.finished:
            return self.command(uid, book, Position(0, 0))
        # Gespeicherten Stand nicht überschreiben: sonst wanderte jedes erneute „weiter“ 5 s zurück.
        # Die tatsächliche Position meldet das Gerät per PlaybackStarted/-Stopped.
        return self.command(uid, book, player.resume_position(book, p.chapter, p.offset_ms), persist_position=False)

    def position_from_context(self, uid: str, token: str | None, offset_ms: int | None) -> tuple[Book, Position] | None:
        """Aktuelle Position aus dem AudioPlayer-Kontext, sonst aus dem gespeicherten Stand."""
        parsed = player.parse_token(token)
        if parsed:
            book = self.book(parsed[0])
            if book and parsed[1] < len(book.chapters):
                return book, Position(parsed[1], int(offset_ms or 0))
        cur = self.current_book(uid)
        if cur:
            book, p = cur
            return book, Position(p.chapter, p.offset_ms)
        return None

    def _save(self, uid: str, book_id: str, chapter: int, offset_ms: int, *, started: bool = True,
              finished: bool = False, reset_failures: bool = False) -> None:
        p = self.store.get_progress(uid, book_id) or Progress(book_id=book_id)
        p.chapter, p.offset_ms, p.updated_at = chapter, max(0, offset_ms), self.clock()
        p.started = p.started or started
        p.finished = finished
        if reset_failures:
            p.failures = 0
        self.store.put_progress(uid, p)

    # --- Ereignisse vom Echo ----------------------------------------------
    def on_started(self, uid: str, token: str, offset_ms: int) -> None:
        parsed = player.parse_token(token)
        if not parsed:
            return
        # Fehlerzähler hier NICHT zurücksetzen: sonst Endlosschleife Started → Failed → Play → Started …
        self._save(uid, parsed[0], parsed[1], offset_ms)
        self.store.put_state(uid, {"book_id": parsed[0], "token": token})

    def on_stopped(self, uid: str, token: str, offset_ms: int) -> None:
        parsed = player.parse_token(token)
        if parsed:
            self._save(uid, parsed[0], parsed[1], offset_ms)

    def on_nearly_finished(self, uid: str, token: str) -> PlayCommand | None:
        parsed = player.parse_token(token)
        book = self.book(parsed[0]) if parsed else None
        if not parsed or not book:
            return None
        nxt = player.next_chapter(book, parsed[1])
        if nxt is None:
            return None
        return self.command(uid, book, Position(nxt, 0), behavior="ENQUEUE", expected_previous_token=token)

    def on_finished(self, uid: str, token: str) -> None:
        parsed = player.parse_token(token)
        book = self.book(parsed[0]) if parsed else None
        if not parsed or not book:
            return
        nxt = player.next_chapter(book, parsed[1])
        if nxt is None:
            self._save(uid, book.book_id, 0, 0, finished=True)
            log("book_finished")
        else:
            # Das nächste Kapitel wurde bereits eingereiht; Fortschritt vorsorglich weiterschalten.
            # Ein komplett gespieltes Kapitel beweist, dass die Wiedergabe funktioniert → Zähler zurück.
            self._save(uid, book.book_id, nxt, 0, reset_failures=True)

    def on_failed(self, uid: str, token: str, offset_ms: int | None, error_type: str) -> PlayCommand | None:
        """Wiedergabefehler (z. B. abgelaufener Link, Netzabbruch): mit frischer URL neu starten."""
        metric("PlaybackFailed", 1)
        log("playback_failed", error_type=error_type)
        parsed = player.parse_token(token)
        book = self.book(parsed[0]) if parsed else None
        if not parsed or not book:
            return None
        p = self.store.get_progress(uid, book.book_id) or Progress(book_id=book.book_id)
        if p.failures >= self.max_retries:
            log("playback_gave_up")
            return None
        p.failures += 1
        if offset_ms is None:  # Position unbekannt: gespeicherte nehmen, wenn gleiches Kapitel
            offset_ms = p.offset_ms if p.chapter == parsed[1] else 0
        p.chapter, p.offset_ms, p.updated_at = parsed[1], max(0, offset_ms), self.clock()
        self.store.put_progress(uid, p)
        pos = player.clamp(book, Position(parsed[1], offset_ms))
        chapter = book.chapters[pos.chapter]
        return PlayCommand(url=self.signer.url_for(chapter.s3_key), token=token, offset_ms=pos.offset_ms,
                           behavior="REPLACE_ALL", expected_previous_token=None, book=book, chapter=pos.chapter)
