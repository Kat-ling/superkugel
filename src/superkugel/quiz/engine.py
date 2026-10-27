"""Rätsel-Logik ohne Alexa: tolerante Antwortprüfung, Auswahl ohne Wiederholung binnen 7 Tagen."""

from __future__ import annotations

import datetime as dt
import random
import re
from difflib import SequenceMatcher

from superkugel.language import numbers_in, plain
from superkugel.quiz.items import BY_ID, ITEMS, KINDS, Item

REPEAT_DAYS = 7
SEEN_TTL_S = 8 * 86400
_FILLER = {"der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "ist", "es", "ich", "glaub", "glaube",
           "mein", "meine", "vielleicht", "aeh", "hm", "hmm", "heisst", "war", "also", "na", "ja", "wohl", "doch",
           "so", "sind", "waere", "wuerde", "sagen", "sag", "mal", "antwort", "die antwort", "im", "in",
           "vom", "von", "und", "auch", "bitte", "naja", "nun", "ah", "oh", "schon", "eh"}
GIVE_UP = re.compile(r"\b(weiss (es )?nicht|weiss ich nicht|keine ahnung|aufloesung|sag es mir|sags mir|sag s mir|"
                     r"verrat|loesung|ich passe|passe|keinen schimmer|kein plan)\b")
EXPLAIN = re.compile(r"^(erklaer|erklaere|warum)\b")


def _words(text: str) -> list[str]:
    return [w for w in plain(text).split() if w not in _FILLER]


def _join_numbers(text: str) -> str:
    """„fünf und siebzig“ → „fünfundsiebzig“ (Alexa trennt Zahlwörter manchmal)."""
    return re.sub(r"\b(ein|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun) und "
                  r"(zwanzig|dreißig|dreissig|vierzig|fünfzig|fuenfzig|sechzig|siebzig|achtzig|neunzig)\b",
                  r"\1und\2", text.lower())


def is_correct(item: Item, answer: str) -> bool:
    """Tolerant: Groß/Klein, Umlaute, Füllwörter, Zahlwörter, kleine Erkennungsfehler, mehrere gültige Antworten.
    Streng genug: Zahlen nie unscharf, Wörter aus der Frage selbst zählen nicht als Antwort."""
    answer = _join_numbers(answer)
    numeric = item.kind == "rechnen" or any(a.isdigit() for a in item.answers)
    if numeric:
        expected = {int(a) for a in item.answers if a.isdigit()} | {
            n for a in item.answers for n in numbers_in(a)}
        found = numbers_in(answer)
        if found:
            return found[-1] in expected or found[0] in expected
    question_words = set(_words(item.question))
    said = " ".join(w for w in _words(answer) if w not in question_words)
    if not said:
        return False
    for accepted in item.answers:
        target = " ".join(w for w in _words(accepted) if w not in question_words) or " ".join(_words(accepted))
        if not target:
            continue
        if re.search(rf"\b{re.escape(target)}\b", said):
            return True
        # Ein Wort falsch erkannt („Großklockner“): Ähnlichkeit bei vergleichbarer Länge – nie bei Zahlen,
        # kurze Wörter strenger („Laute“ ≠ „Leute“)
        if numeric or numbers_in(said) or len(target) < 5 or abs(len(said) - len(target)) > 3:
            continue
        threshold = 0.9 if len(target) <= 6 else 0.85
        if SequenceMatcher(None, said, target).ratio() >= threshold:
            return True
    return False


def gives_up(text: str) -> bool:
    return bool(GIVE_UP.search(plain(text)))


def wants_explanation(text: str) -> bool:
    return bool(EXPLAIN.search(plain(text)))


def prune(seen: dict[str, str], today: dt.date) -> dict[str, str]:
    """Nur Einträge der letzten 7 Tage behalten (Datum je Rätsel)."""
    keep: dict[str, str] = {}
    for item_id, day in seen.items():
        try:
            if (today - dt.date.fromisoformat(day)).days < REPEAT_DAYS:
                keep[item_id] = day
        except ValueError:
            continue
    return keep


def pick(seen: dict[str, str], today: dt.date, last_kind: str | None, rng: random.Random | None = None) -> Item | None:
    """Zufällig, aber gemischt (anderer Typ als zuletzt, wenn möglich); nichts aus den letzten 7 Tagen.
    Ist die Sammlung aufgebraucht, gibt es frisch erzeugte leichte Rechnungen (nie leer)."""
    rng = rng or random.Random()
    recent = prune(seen, today)
    fresh = [i for i in ITEMS if i.item_id not in recent]
    if not fresh:
        for _ in range(50):
            gen = generated(rng)
            if gen.item_id not in recent:
                return gen
        return None
    kinds = [k for k in KINDS if k != last_kind and any(i.kind == k for i in fresh)] or list(KINDS)
    kind = rng.choice([k for k in kinds if any(i.kind == k for i in fresh)])
    return rng.choice([i for i in fresh if i.kind == kind])


_OPS = {"p": ("plus", lambda a, b: a + b), "m": ("minus", lambda a, b: a - b), "x": ("mal", lambda a, b: a * b)}


def generated(rng: random.Random) -> Item:
    """Leichte Kopfrechnung (Ergebnis 1–100). Kennung kodiert die Aufgabe, damit nichts gespeichert werden muss."""
    op = rng.choice(list(_OPS))
    if op == "x":
        a, b = rng.randint(2, 9), rng.randint(2, 10)
    elif op == "m":
        a = rng.randint(10, 60)
        b = rng.randint(1, a - 1)
    else:
        a, b = rng.randint(2, 50), rng.randint(2, 40)
    return _gen_item(f"g{a}{op}{b}")


def _gen_item(item_id: str) -> Item | None:
    m = re.fullmatch(r"g(\d{1,2})([pmx])(\d{1,2})", item_id)
    if not m:
        return None
    a, op, b = int(m[1]), m[2], int(m[3])
    word, fn = _OPS[op]
    result = fn(a, b)
    return Item(item_id, "rechnen", f"Wie viel ist {a} {word} {b}?", (str(result),), "Ganz in Ruhe, Schritt für Schritt.",
                str(result))


def item(item_id: str | None) -> Item | None:
    return BY_ID.get(item_id or "") or _gen_item(item_id or "")
