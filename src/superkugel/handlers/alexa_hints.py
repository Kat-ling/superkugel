"""Erinnerungen, Radio und Rätsel macht Alexa selbst besser (in 1.3 aus der Superkugel entfernt).

Kurzer Hinweis, wie es mit Alexa geht – dann endet die Sitzung, damit sie es gleich direkt zu Alexa sagen kann.
Die KI wird dafür nicht gefragt: sie könnte sonst versprechen, eine Erinnerung angelegt zu haben.
"""

from __future__ import annotations

import re

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from superkugel.handlers.common import Services, end_with
from superkugel.language import plain

# „Spiel Ö3“ landet meist beim Hörbuch-Intent; nur ganze Wörter („Radiokrimi“ ist kein Radio)
_RADIO = re.compile(r"\b(radio|radiosender|sender|oe ?(1|3|eins|drei)|fm ?(4|vier)|kronehit|antenne)\b")


def is_radio(raw: str) -> bool:
    return bool(_RADIO.search(plain(raw)))


def _hint(services: Services, hi: HandlerInput, key: str) -> Response:
    services.count("alexa_hint")
    return end_with(services, hi, services.t(key))


def reminder(services: Services, hi: HandlerInput) -> Response:
    return _hint(services, hi, "hint_reminder")


def radio(services: Services, hi: HandlerInput) -> Response:
    return _hint(services, hi, "hint_radio")


def quiz(services: Services, hi: HandlerInput) -> Response:
    return _hint(services, hi, "hint_quiz")
