"""Regionale Sprachstile.

Wichtig – technische Trennung:
* Spracherkennung: macht immer Alexa (de-DE-Modell). Der Skill kann sie nicht beeinflussen.
* Wortwahl: steuern wir hier über den Systemprompt (regionale Färbung im Text).
* Aussprache/Akzent: hängt allein an der Alexa-Stimme (Hans/Marlene/Vicki/Alexa, alle de-DE).
  Echte Kärntner oder bairische Aussprache gibt es in Alexa nicht.
Deshalb nur *leichte* Färbung in Standardschreibung – keine Lautschrift, die eine
hochdeutsche Stimme hölzern vorlesen würde.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechStyle:
    key: str
    label: str
    prompt: str
    greeting: dict[str, str]  # Anrede "du" | "sie"
    goodbye: dict[str, str]


STYLES: dict[str, SpeechStyle] = {
    "kaernten": SpeechStyle(
        key="kaernten",
        label="Österreichisch mit Kärntner Note",
        prompt=(
            "Sprich österreichisches Deutsch mit leichter Kärntner Färbung: Wörter wie "
            "„Servus“, „gell“, „heuer“, „Jänner“, „Paradeiser“, „Erdäpfel“, „a bissl“, „passt“ "
            "sind willkommen, aber sparsam (höchstens ein, zwei pro Antwort). Schreibe in "
            "normaler Rechtschreibung, keine Lautschrift. Verstehe Kärntner und österreichische "
            "Ausdrücke der Nutzerin („leicht“, „Jause“, „Gatsch“, „lei“), ohne sie zu kommentieren."
        ),
        greeting={"du": "Servus{n}! Schön, dass du da bist. Was gibt's Neues?",
                  "sie": "Grüß Gott{n}! Schön, dass Sie da sind. Was gibt's Neues?"},
        goodbye={"du": "Pfiat di{c}, bis bald!", "sie": "Auf Wiederschauen{c}, bis bald!"},
    ),
    "bayern": SpeechStyle(
        key="bayern",
        label="Bairisch gefärbt",
        prompt=(
            "Sprich Deutsch mit leichter bairischer Färbung: „Servus“, „gell“, „freilich“, "
            "„a bisserl“, „Brotzeit“ sind willkommen, aber sparsam. Normale Rechtschreibung, "
            "keine Lautschrift. Verstehe bairische Ausdrücke der Nutzerin, ohne sie zu kommentieren."
        ),
        greeting={"du": "Servus{n}! Schön, dass du da bist. Was gibt's?",
                  "sie": "Grüß Gott{n}! Schön, dass Sie da sind. Was gibt's?"},
        goodbye={"du": "Pfiat di{c}, bis bald!", "sie": "Pfiat Gott{c}, bis bald!"},
    ),
    "standard": SpeechStyle(
        key="standard",
        label="Klares Standarddeutsch",
        prompt=(
            "Sprich klares, gut verständliches Standarddeutsch. Österreichische und bairische "
            "Ausdrücke der Nutzerin verstehst du selbstverständlich."
        ),
        greeting={"du": "Hallo{n}! Schön, dass du da bist. Worüber magst du plaudern?",
                  "sie": "Guten Tag{n}! Schön, dass Sie da sind. Worüber möchten Sie plaudern?"},
        goodbye={"du": "Bis bald{c}!", "sie": "Auf Wiedersehen{c}, bis bald!"},
    ),
}


def get_style(key: str) -> SpeechStyle:
    return STYLES.get(key, STYLES["standard"])


def personalize(text: str, name: str) -> str:
    """Setzt den Vornamen in Begrüßung/Verabschiedung ein ({n} = " Maria", {c} = ", Maria")."""
    return text.format(n=f" {name}" if name else "", c=f", {name}" if name else "")
