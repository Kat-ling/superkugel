"""Reine Wiedergabelogik: Tokens, Positionen, Kapitelwechsel. Keine Alexa- oder AWS-Abhängigkeit."""

from __future__ import annotations

from dataclasses import dataclass

from superkugel.audiobooks.models import Book

TOKEN_SEP = "|"  # noqa: S105 - kein Passwort, Trennzeichen im AudioPlayer-Token


def make_token(book_id: str, chapter: int) -> str:
    return f"{book_id}{TOKEN_SEP}{chapter}"


def parse_token(token: str | None) -> tuple[str, int] | None:
    if not token or TOKEN_SEP not in token:
        return None
    book_id, _, chapter = token.rpartition(TOKEN_SEP)
    try:
        idx = int(chapter)
    except ValueError:
        return None
    if not book_id or idx < 0:
        return None
    return book_id, idx


@dataclass(frozen=True)
class Position:
    chapter: int
    offset_ms: int


def clamp(book: Book, pos: Position) -> Position:
    if not book.chapters:
        return Position(0, 0)
    chapter = min(max(pos.chapter, 0), len(book.chapters) - 1)
    dur = book.chapters[chapter].duration_ms
    offset = max(pos.offset_ms, 0)
    if dur > 0 and offset >= dur:
        offset = max(dur - 1000, 0)
    return Position(chapter, offset)


def rewind(book: Book, pos: Position, seconds: int) -> Position:
    """Ein Stück zurück; springt bei Bedarf ins Ende des vorherigen Kapitels."""
    target = pos.offset_ms - seconds * 1000
    if target >= 0 or pos.chapter == 0:
        return clamp(book, Position(pos.chapter, max(target, 0)))
    prev = book.chapters[pos.chapter - 1]
    if prev.duration_ms <= 0:
        return Position(pos.chapter - 1, 0)
    return clamp(book, Position(pos.chapter - 1, max(prev.duration_ms + target, 0)))


def forward(book: Book, pos: Position, seconds: int) -> Position | None:
    """Ein Stück vor; None, wenn dabei das Buchende erreicht würde."""
    target = pos.offset_ms + seconds * 1000
    dur = book.chapters[pos.chapter].duration_ms
    if dur <= 0 or target < dur - 1000:
        return Position(pos.chapter, target)
    nxt = pos.chapter + 1
    if nxt >= len(book.chapters):
        return None
    return Position(nxt, max(target - dur, 0))


def next_chapter(book: Book, chapter: int) -> int | None:
    return chapter + 1 if chapter + 1 < len(book.chapters) else None


def previous_chapter(book: Book, chapter: int) -> int:
    return max(chapter - 1, 0)


def resume_position(book: Book, chapter: int, offset_ms: int, back_s: int = 5) -> Position:
    """Beim Fortsetzen ein paar Sekunden zurück, damit der Faden nicht verloren geht."""
    return clamp(book, Position(chapter, max(offset_ms - back_s * 1000, 0)))
