"""Fahrplanauskunft über Alexa: freie Sätze („wann fährt der nächste Zug nach …“), kurze Befehle, KI-Werkzeug.

Die Sitzung bleibt danach still offen (wie beim Ratschen): „und danach?“ nennt die nächste Möglichkeit.
"""

from __future__ import annotations

import re
from typing import Any

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from superkugel.handlers.common import Services, has_session, keep_open, session_attrs
from superkugel.language import fold

_FOLLOW_UP = re.compile(r"^(und )?(danach|dann|später|der nächste|die nächste|den nächsten|der übernächste|"
                        r"noch einer|noch eine|und der nächste|ein späterer|eine spätere)\b")

# Kurze Befehle ohne Ortsangabe (eigene Intents, weil sie kein Trägerwort haben)
BARE = {
    "TransitNextBusIntent": "nächster bus",
    "TransitNextTrainIntent": "nächster zug",
    "TransitLastBusIntent": "letzter bus",
    "TransitLastTrainIntent": "letzter zug",
}


def is_follow_up(hi: HandlerInput, text: str) -> bool:
    return has_session(hi) and bool(session_attrs(hi).get("transit_last")) and bool(_FOLLOW_UP.match(fold(text)))


def answer_text(services: Services, hi: HandlerInput, text: str) -> Response:
    from superkugel.transit import service

    attrs = session_attrs(hi) if has_session(hi) else {}
    after = attrs.get("transit_last") if is_follow_up(hi, text) else None
    ans = service.handle_text(services, text, after)
    services.count("transit")
    if has_session(hi):
        attrs.pop("pending", None)
        if ans.follow_up:
            attrs["transit_last"] = ans.follow_up
        else:
            attrs.pop("transit_last", None)
    return keep_open(services, hi, ans.text, None)


def bare_intent(services: Services, hi: HandlerInput) -> Response:
    from ask_sdk_core.utils import get_intent_name

    return answer_text(services, hi, BARE.get(get_intent_name(hi), "nächster bus"))


def from_tool(services: Services, hi: HandlerInput, args: dict[str, Any]) -> Response:
    """KI-Werkzeug ``fahrplan``: die KI ordnet nur zu (Ziel, Start, Zeit), die Auskunft rechnet der Code."""
    parts = [str(args.get("verkehrsmittel") or ""), "letzte" if args.get("letzte") else ""]
    if args.get("start"):
        parts.append(f"von {args['start']}")
    if args.get("ziel"):
        parts.append(f"nach {args['ziel']}")
    parts.append(str(args.get("zeit") or ""))
    return answer_text(services, hi, " ".join(p for p in parts if p).strip() or "nächster bus")
