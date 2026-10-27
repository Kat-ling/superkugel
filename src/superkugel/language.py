"""Deutsche Wörter → Werte: Zahlwörter, Normalisierung. Gemeinsam für Erinnerungen und Rätsel (ohne KI)."""

from __future__ import annotations

import re
import unicodedata

_UNITS = {"null": 0, "eins": 1, "ein": 1, "eine": 1, "einen": 1, "einem": 1, "einer": 1, "zwei": 2, "zwo": 2,
          "drei": 3, "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9}
_TEENS = {"zehn": 10, "elf": 11, "zwölf": 12, "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16,
          "siebzehn": 17, "achtzehn": 18, "neunzehn": 19}
_TENS = {"zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60,
         "siebzig": 70, "achtzig": 80, "neunzig": 90}
_UNIT_PREFIX = {"ein": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9}


def fold(text: str) -> str:
    """Kleinbuchstaben, überflüssige Zeichen weg; ß und Umlaute bleiben (Zahlwörter wie „dreißig“)."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[^\wäöüß:.,' -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def plain(text: str) -> str:
    """Für tolerante Vergleiche: Umlaute/ß auflösen, nur Buchstaben/Ziffern/Leerzeichen."""
    text = fold(text).replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _below_100(word: str) -> int | None:
    if word in _UNITS:
        return _UNITS[word]
    if word in _TEENS:
        return _TEENS[word]
    if word in _TENS:
        return _TENS[word]
    for tens_word, tens in _TENS.items():
        if word.endswith("und" + tens_word):
            unit = _UNIT_PREFIX.get(word[: -len("und" + tens_word)])
            if unit:
                return tens + unit
    return None


def word_to_int(word: str) -> int | None:
    """„21“, „einundzwanzig“, „hundertzwölf“, „zweihundert“ → Zahl (0–999); sonst None."""
    w = fold(word).replace(" ", "").rstrip(".")
    if w.isdigit():
        return int(w)
    if not w:
        return None
    if "hundert" in w:
        head, _, tail = w.partition("hundert")
        h = 1 if head in ("", "ein", "eins") else _UNIT_PREFIX.get(head)
        if h is None:
            return None
        rest = 0 if not tail else _below_100(tail.removeprefix("und"))
        return None if rest is None else h * 100 + rest
    return _below_100(w)


def numbers_in(text: str) -> list[int]:
    """Alle Zahlen eines Satzes (Ziffern und Zahlwörter), in Reihenfolge."""
    out: list[int] = []
    for tok in fold(text).replace(":", " ").split():
        n = word_to_int(tok.strip(".,"))
        if n is not None and tok not in ("ein", "eine", "einen", "einem", "einer"):
            out.append(n)
    return out
