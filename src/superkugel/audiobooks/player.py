"""Reine Wiedergabelogik: Tokens, Positionen, Kapitelwechsel. Keine Alexa- oder AWS-Abhängigkeit."""

from __future__ import annotations

import re
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


_DURATION = re.compile(r"PT(?:([\d.]+)H)?(?:([\d.]+)M)?(?:([\d.]+)S)?")


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


def jump(book: Book, pos: Position, seconds: int) -> Position | None:
    """Beliebig weit vor (+) oder zurück (-), auch über mehrere Kapitel. Zurück endet am Buchanfang,
    None heißt: Das Buchende würde erreicht."""
    lengths = [c.duration_ms for c in book.chapters]
    target = pos.offset_ms + seconds * 1000
    if min(lengths, default=0) <= 0:  # Länge unbekannt (manche Sendungen): im Kapitel bleiben
        return Position(pos.chapter, max(target, 0))
    target = max(sum(lengths[:pos.chapter]) + target, 0)
    for chapter, length in enumerate(lengths):
        if target < length - 1000:
            return Position(chapter, target)
        target = max(target - length, 0)
    return None


def rewind(book: Book, pos: Position, seconds: int) -> Position:
    return jump(book, pos, -seconds) or pos


def forward(book: Book, pos: Position, seconds: int) -> Position | None:
    return jump(book, pos, seconds)


def duration_seconds(value: str) -> int:
    """Dauer aus dem Alexa-Slot (ISO 8601, zum Beispiel ``PT10M``); 0, wenn sie unklar ist."""
    match = _DURATION.fullmatch(value)
    if not match or not any(match.groups()):
        return 0
    hours, minutes, seconds = (float(g or 0) for g in match.groups())
    return round(hours * 3600 + minutes * 60 + seconds)


def next_chapter(book: Book, chapter: int) -> int | None:
    return chapter + 1 if chapter + 1 < len(book.chapters) else None


def previous_chapter(book: Book, chapter: int) -> int:
    return max(chapter - 1, 0)


def resume_position(book: Book, chapter: int, offset_ms: int, back_s: int = 5) -> Position:
    """Beim Fortsetzen ein paar Sekunden zurück, damit der Faden nicht verloren geht."""
    return clamp(book, Position(chapter, max(offset_ms - back_s * 1000, 0)))
