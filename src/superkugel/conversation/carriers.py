"""Trägerwörter für freie Rede.

AMAZON.SearchQuery braucht laut Alexa-Doku eine Trägerphrase; ein Beispielsatz darf nicht nur
aus dem Slot bestehen. Alexa liefert aber nur den Slot-Inhalt, nicht das Trägerwort. Deshalb
bekommt jedes Trägerwort einen eigenen Intent – so lässt sich der Satz vollständig
rekonstruieren („warum“ + „wird alles teurer“), statt „wann“ und „warum“ zu verwechseln.

Weitere Wörter nach dem Träger landen automatisch im Slot („ich“ + „möchte wissen …“).
Aus dieser Liste erzeugt ``scripts/build_interaction_model.py`` das Interaction Model.
"""

from __future__ import annotations

import re

CARRIERS: tuple[str, ...] = (
    # Fragewörter
    "was", "wer", "wen", "wem", "wessen", "wie", "wo", "woher", "wohin", "wann", "warum",
    "wieso", "weshalb", "welche", "welcher", "welches", "wie viel", "wie viele", "wozu", "womit",
    # Gesprächseinstiege
    "kannst du", "könntest du", "weißt du", "glaubst du", "meinst du", "findest du",
    "erzähl mir", "erzähl", "erklär mir", "erklär", "sag mal", "sag mir", "hör mal",
    "stell dir vor", "ich hab eine frage", "eine frage",
    # Satzanfänge in normaler Rede
    "ich", "mir", "mich", "mein", "meine", "wir", "unser", "unsere", "du", "dir", "dich",
    "und", "aber", "also", "na", "naja", "ja", "nein", "doch", "gut", "schon",
    "das", "der", "die", "es", "dann", "jetzt", "heute", "gestern", "morgen", "vorhin",
    "gibt es", "ist es", "ist das", "hast du", "bist du", "hab ich", "habe ich",
    "servus", "grüß gott", "hallo", "guten morgen", "guten abend", "danke für",
    "such", "suche", "such mir", "finde", "find mir",
    "bei uns", "im garten", "meine tochter", "mein sohn", "mein enkel", "meine enkelin",
)


def chat_intent_name(carrier: str) -> str:
    slug = carrier.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    parts = re.split(r"[^a-z]+", slug.lower())
    return "Chat" + "".join(p.capitalize() for p in parts if p) + "Intent"


INTENT_TO_CARRIER: dict[str, str] = {chat_intent_name(c): c for c in CARRIERS}


def is_chat_intent(intent_name: str) -> bool:
    return intent_name in INTENT_TO_CARRIER


def reconstruct(intent_name: str, query: str | None) -> str:
    """Setzt Trägerwort und Slot-Inhalt wieder zu einem Satz zusammen."""
    carrier = INTENT_TO_CARRIER.get(intent_name, "")
    return " ".join(p for p in (carrier, (query or "").strip()) if p).strip()
