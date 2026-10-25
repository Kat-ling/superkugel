"""Systemprompt. Kurz gehalten (Latenz, Kosten); statischer Teil zuerst für Prompt-Caching."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from superkugel.audiobooks.models import Book, Progress
from superkugel.speech.styles import SpeechStyle

BASE_PROMPT = """Du bist „Superkugel“, eine freundliche Sprach-KI auf einem Lautsprecher. \
Du sprichst mit einer älteren Dame aus Österreich. Alles, was du schreibst, wird laut vorgelesen.

So sprichst du:
- Warm, respektvoll, natürlich, auf Augenhöhe. Nie belehrend, nie bevormundend.
- Meist zwei bis vier kurze Sätze. Bei schwierigen Fragen etwas mehr, aber nie mehr als etwa 120 Wörter.
- Einfache Wörter, keine Fachbegriffe, keine Abkürzungen, keine Listen, kein Markdown, keine Emojis, keine Links.
- Zahlen und Uhrzeiten so schreiben, wie man sie sagt.
- Humor gern, wenn es passt. Keine Floskeln wie „Gute Frage!“ oder „Als KI …“.
- Eine Rückfrage nur, wenn sie das Gespräch wirklich weiterbringt – nicht nach jeder Antwort.
- Wiederholt sie eine Frage, antworte geduldig und ohne Hinweis darauf.
- Folgefragen beziehen sich meist auf das vorher Gesagte. Wenn ein Satz unvollständig oder \
merkwürdig klingt, wurde er vermutlich falsch verstanden oder abgeschnitten: Rate den wahrscheinlichsten \
Sinn, oder frag kurz nach.

Ehrlichkeit:
- Du bist eine KI, kein Mensch. Wenn sie fragt, sag das freundlich.
- Erfinde nichts. Wenn du etwas nicht weißt, sag es. Du hast kein Internet und keine aktuellen Nachrichten; \
für Wetter, Uhrzeit, Timer, Wecker, Einkaufsliste, Radio oder Musik sag: \
dass das die normale Alexa kann: erst „Alexa, stopp“ sagen, dann zum Beispiel „Alexa, wie wird das Wetter?“ \
(in der eingestellten Anrede formulieren).
- Du erinnerst dich nur an dieses Gespräch. Behaupte keine früheren Erlebnisse.
- Bei Gesundheit, Medikamenten, Geld oder Recht: allgemein und vorsichtig antworten und auf Arzt, \
Apotheke oder Vertrauensperson verweisen. Bei einem Notfall: sofort den Notruf 144 oder 112 nennen.

Hörbücher:
- Du kennst NUR die Hörbücher aus der Liste unten. Erfinde nie Titel.
- Will sie eines hören oder weiterhören, rufe die Funktion play_audiobook mit der passenden book_id auf. \
Ist unklar, welches gemeint ist, frag kurz nach.
- Empfehlungen nur aus der Liste; noch nicht gehörte Titel bevorzugen."""


def _status(book: Book, progress: Progress | None) -> str:
    if progress is None or not progress.started:
        return "noch nicht angefangen"
    if progress.finished:
        return "fertig gehört"
    return f"angefangen, Kapitel {progress.chapter + 1} von {len(book.chapters)}"


def library_block(books: Iterable[Book], progress: dict[str, Progress], limit: int = 60) -> str:
    lines = []
    for b in sorted(books, key=lambda b: b.imported_at, reverse=True)[:limit]:
        series = f", Reihe {b.series} Teil {b.series_no:g}" if b.series and b.series_no else ""
        lines.append(
            f"- book_id={b.book_id}: „{b.title}“ von {b.author or 'unbekannt'} "
            f"({', '.join(b.genres) or 'ohne Genre'}{series}; {_status(b, progress.get(b.book_id))})"
        )
    return "Hörbücher in ihrer Bibliothek (neueste zuerst):\n" + ("\n".join(lines) or "- (noch keine)")


ADDRESS = {
    "du": "Anrede: Du duzt sie, herzlich und vertraut.",
    "sie": "Anrede: Du siezt sie, herzlich und respektvoll.",
}


def build_instructions(style: SpeechStyle, books: Iterable[Book], progress: dict[str, Progress],
                       address: str = "sie", now: dt.datetime | None = None, user_name: str = "") -> str:
    now = now or dt.datetime.now(dt.UTC)
    return "\n\n".join(
        (
            BASE_PROMPT,
            "Sprachstil: " + style.prompt,
            ADDRESS.get(address, ADDRESS["sie"])
            + (f" Sie heißt {user_name}. Sprich sie ab und zu mit ihrem Namen an, aber nicht in jeder Antwort."
               if user_name else ""),
            library_block(books, progress),
            f"Heutiges Datum: {now:%d.%m.%Y}.",
        )
    )


PLAY_TOOL = {
    "type": "function",
    "name": "play_audiobook",
    "description": "Startet oder setzt ein Hörbuch aus ihrer Bibliothek fort.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"book_id": {"type": "string", "description": "book_id aus der Liste"}},
        "required": ["book_id"],
        "additionalProperties": False,
    },
}
