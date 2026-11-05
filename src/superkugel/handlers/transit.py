"""Fahrplanauskunft über Alexa: freie Sätze („wann fährt der nächste Zug nach …“), kurze Befehle, KI-Werkzeug.

Die Sitzung bleibt danach still offen (wie beim Ratschen): „und danach?“ nennt die nächste Möglichkeit,
„genauer“ die Umstiege der Kurzfassung, „und zurück?“ die Rückfahrt. Gibt es einen Ort mehrfach, fragt die
Superkugel „Meinst du …?“. Folgefragen gelten nur als ganzer kurzer Satz – „dann mach ich mir einen Kaffee“ ist
ein Gespräch. Nach einer KI-Antwort ist das Fahrplan-Thema beendet.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from superkugel.handlers.common import Services, has_session, keep_open, session_attrs
from superkugel.language import fold, word_to_int
from superkugel.transit.ask import parse, parse_dest

_VEHICLE = r"(bus|autobus|postbus|zug|bahn)"
_FOLLOW_UP = re.compile(rf"(und )?(wann )?(fährt |geht |kommt )?(danach|dann|später|der nächste|die nächste|"
                        rf"den nächsten|der übernächste|noch einer|noch eine|noch einen|ein späterer|eine spätere|"
                        rf"einen späteren)( {_VEHICLE})?( danach| dann| später)?( noch)?( bitte)?")
_DETAIL = re.compile(r"(und )?(genauer|ganz genau|wie genau|bitte genauer|genauer bitte|einzelheiten|die umstiege|"
                     r"wo (muss ich |soll ich |muss man )?umsteigen|wo steige ich um|dann)( bitte)?")
# „und dann nach Seeort“: neue Frage mit neuem Ziel
_NEW_TARGET = re.compile(rf"(und )?(wann )?(dann |danach |(der|die|den) nächsten? ({_VEHICLE} )?(bitte )?)"
                         r"nach (?!dem\b|der\b|den\b|des\b|einem\b|einer\b|hause\b)\S")
# „und zurück“, „wie komm ich wieder heim“, „am Nachmittag zurück“: nur diese Wörter – „ich ruf dich zurück“ ist Gespräch
_BACK_CORE = re.compile(r"\b(zurück|retour|rückfahrt|rückweg|rückreise|heimfahrt|heimweg|heim|hause)\b")
_BACK_VOCABULARY = """und wie wann wo komm komme kommen ich wir man fahr fahre fahren fährt geht gehts geht's es
    der die das den dem ein eine einen bus autobus postbus zug bahn nächste nächster nächsten letzte letzter letzten
    wieder denn dann bitte noch am um gegen ab heute morgen übermorgen abend abends nachmittag nachmittags vormittag
    vormittags früh mittag mittags in uhr halb viertel dreiviertel vor nach montag dienstag mittwoch donnerstag freitag
    samstag sonntag zurück retour rückfahrt rückweg rückreise heimfahrt heimweg heim hause"""
_BACK_WORDS = frozenset(_BACK_VOCABULARY.split())

# Kurze Befehle ohne Ortsangabe (eigene Intents, weil sie kein Trägerwort haben)
BARE = {
    "TransitNextBusIntent": "nächster bus",
    "TransitNextTrainIntent": "nächster zug",
    "TransitLastBusIntent": "letzter bus",
    "TransitLastTrainIntent": "letzter zug",
}


def _is_back(t: str) -> bool:
    words = t.replace(".", " ").replace(",", " ").split()
    return bool(_BACK_CORE.search(t)) and all(w in _BACK_WORDS or word_to_int(w) is not None for w in words)


def _follow_kind(hi: HandlerInput, text: str) -> str:
    """"day" (Antwort auf „Welchen Tag?“), "back" (Rückfahrt), "detail" (Umstiege der Kurzfassung),
    "next" (nächste Möglichkeit) oder ""."""
    last = session_attrs(hi).get("transit_last") if has_session(hi) else None
    if not last:
        return ""
    t = fold(text).rstrip(".,? ")
    if last.get("ask_day"):
        return "day" if parse(text, dt.datetime(2000, 1, 3, 12)).day_said else ""
    if (last.get("places") or {}).get("dest") and _is_back(t):
        return "back"
    if last.get("short_t") is not None and _DETAIL.fullmatch(t):
        return "detail"
    if not last.get("next_t") or not _FOLLOW_UP.fullmatch(t):
        return ""
    # „der nächste Bus“ nach einer Zugauskunft ist eine neue Frage
    said = parse(text, dt.datetime(2000, 1, 3, 12)).mode
    asked = str(last.get("text", "")).split(" ")[0]
    return "" if said != "any" and {"train": "zug", "bus": "bus"}[said] != asked else "next"


def is_follow_up(hi: HandlerInput, text: str) -> bool:
    return bool(_follow_kind(hi, text))


def is_new_target(services: Services, hi: HandlerInput, text: str) -> bool:
    """„Und dann nach Seeort“ direkt nach einer Auskunft – nur, wenn das Ziel eine bekannte Haltestelle ist."""
    from superkugel.transit import service

    if not (has_session(hi) and session_attrs(hi).get("transit_last") and _NEW_TARGET.match(fold(text))):
        return False
    dest = parse_dest(text)
    return bool(dest) and service.knows_place(services, dest)


def answer_text(services: Services, hi: HandlerInput, text: str, chosen: dict[str, str] | None = None) -> Response:
    from superkugel.transit import service

    attrs = session_attrs(hi) if has_session(hi) else {}
    kind = "" if chosen else _follow_kind(hi, text)
    if kind == "day":  # „Welchen Tag?“ – „am Donnerstag“: die offene Frage mit dem Tag
        text, kind = f"{attrs['transit_last'].get('text', '')} {text}", ""
    after = attrs.get("transit_last") if kind else None
    ans = service.handle_text(services, text, after, detail=kind == "detail", chosen=chosen, back=kind == "back")
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


def thanks_intent(services: Services, hi: HandlerInput, started: float) -> Response:
    """„Danke“ beendet das Fahrplan-Thema; ohne Fahrplan-Thema ist es ein normaler Gesprächssatz."""
    attrs = session_attrs(hi)
    if attrs.get("transit_last") or attrs.get("pending") == "transit_confirm":
        attrs.pop("transit_last", None)
        attrs.pop("transit_confirm", None)
        attrs.pop("pending", None)
        return keep_open(services, hi, services.t("transit_thanks"), None)
    from superkugel.handlers.conversation import handle_chat_text

    return handle_chat_text(services, hi, "danke", started)


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

    ans = service.handle_text(services, tool_text(args))
    if ans.kind == "unknown" and said and parse_dest(said):
        retry = service.handle_text(services, said)
        if retry.kind != "unknown":
            ans = retry
    return _respond(services, hi, ans)
