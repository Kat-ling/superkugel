"""Fahrplanauskunft über Alexa: freie Sätze („wann fährt der nächste Zug nach …“), kurze Befehle, KI-Werkzeug.

Die Sitzung bleibt danach still offen (wie beim Ratschen): „und danach?“ nennt die nächste Möglichkeit,
„genauer“ die Umstiege der Kurzfassung. Gibt es einen Ort mehrfach, fragt die Superkugel „Meinst du …?“.
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
_DETAIL = re.compile(r"^(und )?(genauer|ganz genau|wie genau|bitte genauer|einzelheiten|die umstiege|"
                     r"wo (muss ich |soll ich |muss man )?umsteigen|und dann)\b")

# Kurze Befehle ohne Ortsangabe (eigene Intents, weil sie kein Trägerwort haben)
BARE = {
    "TransitNextBusIntent": "nächster bus",
    "TransitNextTrainIntent": "nächster zug",
    "TransitLastBusIntent": "letzter bus",
    "TransitLastTrainIntent": "letzter zug",
}


def _follow_kind(hi: HandlerInput, text: str) -> str:
    """"detail" (Umstiege der Kurzfassung), "next" (nächste Möglichkeit) oder ""."""
    last = session_attrs(hi).get("transit_last") if has_session(hi) else None
    if not last:
        return ""
    t = fold(text)
    if last.get("short_t") is not None and _DETAIL.match(t):
        return "detail"
    return "next" if _FOLLOW_UP.match(t) else ""


def is_follow_up(hi: HandlerInput, text: str) -> bool:
    return bool(_follow_kind(hi, text))


def answer_text(services: Services, hi: HandlerInput, text: str, chosen: dict[str, str] | None = None) -> Response:
    from superkugel.transit import service

    attrs = session_attrs(hi) if has_session(hi) else {}
    kind = "" if chosen else _follow_kind(hi, text)
    after = attrs.get("transit_last") if kind else None
    ans = service.handle_text(services, text, after, detail=kind == "detail", chosen=chosen)
    return _respond(services, hi, ans)


def _respond(services: Services, hi: HandlerInput, ans: Any) -> Response:
    services.count("transit")
    if has_session(hi):
        attrs = session_attrs(hi)
        attrs.pop("pending", None)
        attrs.pop("transit_confirm", None)
        if ans.confirm:
            attrs["pending"] = "transit_confirm"
            attrs["transit_confirm"] = {**ans.confirm, "i": 0}
            return keep_open(services, hi, ans.text, ans.text)
        if ans.follow_up:
            attrs["transit_last"] = ans.follow_up
        else:
            attrs.pop("transit_last", None)
    return keep_open(services, hi, ans.text, None)


def confirm_yes(services: Services, hi: HandlerInput) -> Response:
    """„Ja“ auf „Meinst du …?“: dieselbe Frage mit dem bestätigten Ort."""
    c = session_attrs(hi).pop("transit_confirm", None) or {}
    choices, i = c.get("choices") or [], int(c.get("i", 0))
    if not choices or i >= len(choices):
        return keep_open(services, hi, services.t("transit_confirm_none"), None)
    chosen = {**(c.get("chosen") or {}), c.get("role", "dest"): choices[i]}
    return answer_text(services, hi, c.get("text", ""), chosen=chosen)


def confirm_no(services: Services, hi: HandlerInput) -> Response:
    """„Nein“: den nächsten gleichnamigen Ort anbieten, danach um eine genauere Angabe bitten."""
    from superkugel.transit import service

    attrs = session_attrs(hi)
    c = attrs.pop("transit_confirm", None) or {}
    choices, i = c.get("choices") or [], int(c.get("i", 0)) + 1
    name = service.place_name(services, choices[i]) if i < len(choices) else ""
    if not name:
        return keep_open(services, hi, services.t("transit_confirm_none"), None)
    attrs["pending"] = "transit_confirm"
    attrs["transit_confirm"] = {**c, "i": i}
    q = services.t("transit_confirm_other", name=name)
    return keep_open(services, hi, q, q)


def confirm_text(services: Services, hi: HandlerInput, text: str) -> Response | None:
    """Freie Antwort auf „Meinst du …?“. None = keine Antwort darauf (normal weiter)."""
    from superkugel.transit import service

    t = fold(text)
    if re.match(r"^(ja|genau|richtig|stimmt|freilich|na klar)\b", t):
        return confirm_yes(services, hi)
    if re.match(r"^(nein\b|na$|nicht$|eh nicht)", t):
        return confirm_no(services, hi)
    c = session_attrs(hi).get("transit_confirm") or {}
    choices = c.get("choices") or []
    said = re.sub(r"^(ich mein(e)?|nach|in|das in|das)\s+", "", t)
    if choices and said:  # „in Salzburg“, „das bei Graz“: Zusatz zum gefragten Ort
        import datetime as dt

        from superkugel.transit.ask import parse

        q = parse(c.get("text", ""), dt.datetime(2000, 1, 3, 12))
        base = q.origin if c.get("role") == "origin" else q.dest
        gid = (service.find_gid(services, f"{base} in {said}") if base else "") or service.find_gid(services, said)
        if gid:
            session_attrs(hi).pop("transit_confirm", None)
            return answer_text(services, hi, c.get("text", ""), chosen={**(c.get("chosen") or {}),
                                                                       c.get("role", "dest"): gid})
    return None


def detail_intent(services: Services, hi: HandlerInput, started: float) -> Response:
    """„genauer“: nach einer Kurzfassung alle Umstiege; sonst ist das Gespräch gemeint („erzähl genauer“)."""
    if _follow_kind(hi, "genauer") == "detail":
        return answer_text(services, hi, "genauer")
    from superkugel.handlers.conversation import handle_chat_text

    return handle_chat_text(services, hi, "genauer, bitte", started)


def bare_intent(services: Services, hi: HandlerInput) -> Response:
    from ask_sdk_core.utils import get_intent_name

    return answer_text(services, hi, BARE.get(get_intent_name(hi), "nächster bus"))


def tool_text(args: dict[str, Any]) -> str:
    """KI-Werkzeug ``fahrplan`` → Satz für den Fahrplan-Leser („zug von X nach Y bei Z morgen um 8“)."""
    parts = [str(args.get("verkehrsmittel") or ""), "letzte" if args.get("letzte") else ""]
    if args.get("start"):
        parts.append(f"von {args['start']}")
    if args.get("ziel"):
        near = str(args.get("naehe") or "").strip()
        parts.append(f"nach {args['ziel']}" + (f" bei {near}" if near else ""))
    parts.append(str(args.get("zeit") or ""))
    return " ".join(p for p in parts if p).strip() or "nächster bus"


def from_tool(services: Services, hi: HandlerInput, args: dict[str, Any], said: str = "") -> Response:
    """KI-Werkzeug ``fahrplan``: die KI ordnet nur zu (Ziel, Start, Zeit), die Auskunft rechnet der Code.
    Kennt der Fahrplan das Ziel der KI nicht, zählt der Originalsatz (falls er selbst ein Ziel nennt)."""
    from superkugel.transit import service
    from superkugel.transit.ask import parse_dest

    ans = service.handle_text(services, tool_text(args))
    if ans.kind == "unknown" and said and parse_dest(said):
        retry = service.handle_text(services, said)
        if retry.kind != "unknown":
            ans = retry
    return _respond(services, hi, ans)
