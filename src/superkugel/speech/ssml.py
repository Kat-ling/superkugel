"""SSML-Erzeugung für Alexa: sicheres Escaping, Stimme, Tempo, Pausen, Längenbegrenzung."""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

MAX_SPEECH_CHARS = 1400  # deutlich unter dem Alexa-Limit (8000 Zeichen), hält Antworten hörbar kurz
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_MARKDOWN = re.compile(r"(\*\*|__|`|#+\s|^\s*[-*•]\s+)", re.MULTILINE)
_URL = re.compile(r"https?://\S+")


def clean_text(text: str) -> str:
    """Entfernt Markdown/Links, die beim Vorlesen stören."""
    text = _URL.sub("", text)
    text = _MARKDOWN.sub("", text)
    text = re.sub(r"\s*\n+\s*", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def limit_length(text: str, max_chars: int = MAX_SPEECH_CHARS) -> str:
    """Kürzt an einer Satzgrenze, damit nie mitten im Wort abgebrochen wird."""
    if len(text) <= max_chars:
        return text
    out = ""
    for sentence in _SENTENCE_END.split(text):
        if len(out) + len(sentence) + 1 > max_chars:
            break
        out = f"{out} {sentence}".strip()
    return out or text[: max_chars - 1].rsplit(" ", 1)[0] + "…"


def to_ssml(text: str, voice: str = "alexa", rate: str = "100%", slow: bool = False) -> str:
    """Wandelt Klartext in SSML. Satzpausen etwas länger für ältere Zuhörerinnen."""
    body = escape(limit_length(clean_text(text)))
    body = _SENTENCE_END.sub(' <break time="350ms"/> ', body)
    effective_rate = "85%" if slow else rate
    if effective_rate != "100%":
        body = f'<prosody rate="{escape(effective_rate)}">{body}</prosody>'
    if voice and voice.lower() != "alexa":
        body = f'<voice name="{escape(voice)}"><lang xml:lang="de-DE">{body}</lang></voice>'
    return f"<speak>{body}</speak>"
