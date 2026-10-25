"""Deterministische, fehlertolerante Titelsuche (ohne Sprachmodell)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from superkugel.audiobooks.models import Book, Progress

_STOPWORDS = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "mein", "meinen",
    "meine", "meinem", "mir", "bitte", "hörbuch", "hoerbuch", "buch", "hörspiel", "von", "vom",
    "spiel", "spiele", "abspielen", "vorlesen", "lies", "hören", "mal", "doch", "mit", "noch",
}

# Genre-Synonyme -> kanonisches Genre (wie im Manifest verwendet, kleingeschrieben)
GENRE_SYNONYMS: dict[str, str] = {
    "gartenkrimi": "gartenkrimi", "gartenkrimis": "gartenkrimi", "garten krimi": "gartenkrimi",
    "krimi": "krimi", "krimis": "krimi", "kriminalroman": "krimi", "detektivgeschichte": "krimi",
    "regionalkrimi": "regionalkrimi", "regionalkrimis": "regionalkrimi", "heimatkrimi": "regionalkrimi",
    "alpenkrimi": "regionalkrimi", "österreich krimi": "regionalkrimi",
    "hörspiel": "hörspiel", "hörspiele": "hörspiel", "hoerspiel": "hörspiel",
    "roman": "roman", "romane": "roman", "geschichte": "geschichte", "geschichten": "geschichte",
    "märchen": "märchen", "humor": "humor", "lustiges": "humor",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("ß", "ss")
    text = re.sub(r"[^\wäöü ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t not in _STOPWORDS]


def detect_genre(text: str) -> str | None:
    norm = normalize(text)
    # längste Synonyme zuerst, damit "gartenkrimi" vor "krimi" greift
    for syn in sorted(GENRE_SYNONYMS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(normalize(syn))}\b", norm):
            return GENRE_SYNONYMS[syn]
    return None


def book_has_genre(book: Book, genre: str) -> bool:
    gs = {normalize(g) for g in book.genres}
    if genre == "krimi":  # Gartenkrimis und Regionalkrimis sind auch Krimis
        return bool(gs & {"krimi", "gartenkrimi", "regionalkrimi"})
    return normalize(genre) in gs


@dataclass(frozen=True)
class Match:
    book: Book
    score: float


def score(query: str, book: Book) -> float:
    q = " ".join(_tokens(query))
    if not q:
        return 0.0
    candidates = [book.title, f"{book.title} {book.author}", book.series, f"{book.series} {book.series_no or ''}"]
    best = 0.0
    q_tokens = set(q.split())
    for cand in candidates:
        c = " ".join(_tokens(cand))
        if not c:
            continue
        ratio = SequenceMatcher(None, q, c).ratio()
        c_tokens = set(c.split())
        overlap = len(q_tokens & c_tokens) / max(1, len(q_tokens))
        # Teilwort-Treffer ("kräuterbeet" in "mord im kräuterbeet")
        partial = 1.0 if q in c else 0.0
        best = max(best, 0.5 * ratio + 0.4 * overlap + 0.3 * partial)
    return min(best, 1.0)


def find_books(query: str, books: list[Book], threshold: float = 0.45) -> list[Match]:
    matches = [Match(b, score(query, b)) for b in books]
    return sorted((m for m in matches if m.score >= threshold), key=lambda m: m.score, reverse=True)


def best_match(query: str, books: list[Book]) -> tuple[Book | None, list[Match]]:
    """Eindeutiger Treffer oder (None, Kandidaten), wenn nachgefragt werden sollte."""
    matches = find_books(query, books)
    if not matches:
        return None, []
    if len(matches) == 1 or matches[0].score - matches[1].score >= 0.12 or matches[0].score >= 0.9:
        return matches[0].book, matches
    return None, matches[:3]


def pick_by_genre(books: list[Book], genre: str | None, progress: dict[str, Progress],
                  newest: bool = False) -> Book | None:
    """Auswahl nach Genre: angefangenes Buch zuerst, sonst Neuestes ungehörtes, sonst Neuestes."""
    pool = [b for b in books if genre is None or book_has_genre(b, genre)]
    if not pool:
        return None
    by_new = sorted(pool, key=lambda b: b.imported_at, reverse=True)
    if newest:
        return by_new[0]
    in_progress = [b for b in pool if (p := progress.get(b.book_id)) and p.started and not p.finished]
    if in_progress:
        return max(in_progress, key=lambda b: progress[b.book_id].updated_at)
    unheard = [b for b in by_new if b.book_id not in progress or not progress[b.book_id].started]
    return (unheard or by_new)[0]
