"""Deutsche Wörter: Normalisierung und Namen von Wochentagen/Monaten (ohne KI)."""

from __future__ import annotations

import re
import unicodedata

WEEKDAY_NAMES = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONTH_NAMES = ("Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
               "November", "Dezember")


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
