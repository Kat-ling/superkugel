"""Deutsche Wörter: Normalisierung, Zahlwörter, Namen von Wochentagen/Monaten (ohne KI)."""

from __future__ import annotations

import re
import unicodedata

WEEKDAY_NAMES = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONTH_NAMES = ("Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
               "November", "Dezember")

_UNITS = {"null": 0, "eins": 1, "ein": 1, "eine": 1, "zwei": 2, "zwo": 2, "drei": 3, "vier": 4, "fünf": 5,
          "sechs": 6, "sieben": 7, "acht": 8, "neun": 9}
_TEENS = {"zehn": 10, "elf": 11, "zwölf": 12, "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16,
          "siebzehn": 17, "achtzehn": 18, "neunzehn": 19}
_TENS = {"zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40, "fünfzig": 50}
_UNIT_PREFIX = {"ein": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9}


def fold(text: str) -> str:
    """Kleinbuchstaben, überflüssige Zeichen weg; ß und Umlaute bleiben."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[^\wäöüß:.,' -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def plain(text: str) -> str:
    """Für tolerante Vergleiche: Umlaute/ß auflösen, nur Buchstaben/Ziffern/Leerzeichen."""
    text = fold(text).replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def word_to_int(word: str) -> int | None:
    """„21“, „acht“, „einundzwanzig“ → Zahl (0–59, genug für Uhrzeiten); sonst None."""
    w = fold(word).replace(" ", "").rstrip(".")
    if w.isdigit():
        return int(w)
    for table in (_UNITS, _TEENS, _TENS):
        if w in table:
            return table[w]
    for tens_word, tens in _TENS.items():
        if w.endswith("und" + tens_word):
            unit = _UNIT_PREFIX.get(w[: -len("und" + tens_word)])
            if unit:
                return tens + unit
    return None
