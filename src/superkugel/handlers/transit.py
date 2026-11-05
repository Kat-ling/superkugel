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

from superkugel.handlers.common import Services, has_session, keep_open, session_attrs, uid
from superkugel.language import fold, word_to_int
from superkugel.services.logs import log
from superkugel.services.usage import local_now
from superkugel.transit.ask import only_says_when, parse, parse_dest
from superkugel.transit.trip import Change, Trip

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

RETURN_GAP_MIN = 10  # Rückfahrt frühestens 10 Minuten nach der Ankunft

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


def _trip(hi: HandlerInput) -> Trip | None:
    return Trip.from_dict(session_attrs(hi).get("trip")) if has_session(hi) else None


def _save_trip(services: Services, hi: HandlerInput, trip: dict[str, Any] | None) -> None:
    """Stand neben dem Gespräch ablegen, damit „Stopp“ oder ein Neustart ihn nicht löscht (nur der Stand zählt)."""
    window = services.settings.resume_window_s
    if window <= 0:
        return
    try:
        user = uid(hi)
        turns = (services.store.get_conversation(user) or {}).get("turns") or []
        if trip or turns:
            services.store.put_conversation(user, {"turns": turns, **({"trip": trip} if trip else {})}, window)
        else:
            services.store.delete_conversation(user)
    except Exception as exc:  # noqa: BLE001 - ohne Gedächtnis geht die Auskunft trotzdem
        log("trip_save_failed", error=type(exc).__name__)


def restore_trip(services: Services, hi: HandlerInput, snap: dict[str, Any] | None = None) -> None:
    """Stand aus dem Gesprächseintrag zurück in die Sitzung."""
    try:
        snap = snap if snap is not None else services.store.get_conversation(uid(hi))
    except Exception as exc:  # noqa: BLE001
        log("trip_read_failed", error=type(exc).__name__)
        return
    if trip := Trip.from_dict((snap or {}).get("trip")):
        session_attrs(hi)["trip"] = trip.to_dict()


def end_session_keep_trip(services: Services, hi: HandlerInput) -> None:
    """Bewusstes Beenden: Das Gespräch endet, nur eine laufende Reise bleibt kurz gemerkt."""
    trip = session_attrs(hi).get("trip") if has_session(hi) else None
    if trip and services.settings.resume_window_s > 0:
        services.store.put_conversation(uid(hi), {"turns": [], "trip": trip}, services.settings.resume_window_s)
    else:
        services.store.delete_conversation(uid(hi))


def _follow_kind(hi: HandlerInput, text: str) -> str:
    """"day" (Antwort auf „Welchen Tag?“), "back" (Rückfahrt), "detail" (Umstiege der Kurzfassung),
    "when" (nur Zeit oder Tag ändert sich), "next" (nächste Möglichkeit) oder ""."""
    trip = _trip(hi)
    if not trip:
        return ""
    t = fold(text).rstrip(".,? ")
    probe = parse(text, dt.datetime(2000, 1, 3, 12))
    if trip.open == "day":
        return "day" if probe.day_said else ""
    if trip.dest and _is_back(t):
        return "back"
    if trip.short and _DETAIL.fullmatch(t):
        return "detail"
    if only_says_when(text):
        return "when"
    if trip.dep is None or trip.last or not _FOLLOW_UP.fullmatch(t):
        return ""
    # „der nächste Bus“ nach einer Zugauskunft ist eine neue Frage
    return "" if probe.mode != "any" and probe.mode != trip.mode else "next"


def _change(services: Services, kind: str, text: str) -> Change:
    """Erkannte Nachfrage → Änderung am Reise-Stand. Tag nur, wenn er genannt wurde."""
    q = parse(text, local_now(services.settings, services.now()))
    tag = q.day.isoformat() if q.day_said and q.day else ""
    mode = "" if q.mode == "any" else q.mode
    if kind == "back":
        return Change("rueckfahrt", tag=tag, zeit_s=q.time_s, bezug="nach_ankunft", versatz_min=RETURN_GAP_MIN,
                      mode=mode, last=True if q.last else None)
    if kind == "when":
        return Change("aendern", tag=tag, zeit_s=q.time_s)
    return Change("genauer" if kind == "detail" else "spaeter", mode=mode)


def is_follow_up(hi: HandlerInput, text: str) -> bool:
    return bool(_follow_kind(hi, text))


def is_new_target(services: Services, hi: HandlerInput, text: str) -> bool:
    """„Und dann nach Seeort“ direkt nach einer Auskunft – nur, wenn das Ziel eine bekannte Haltestelle ist."""
    from superkugel.transit import service

    if not (has_session(hi) and session_attrs(hi).get("trip") and _NEW_TARGET.match(fold(text))):
        return False
    dest = parse_dest(text)
    return bool(dest) and service.knows_place(services, dest)


def answer_text(services: Services, hi: HandlerInput, text: str, chosen: dict[str, str] | None = None) -> Response:
    from superkugel.transit import service

    kind = "" if chosen else _follow_kind(hi, text)
    trip = _trip(hi) if kind else None
    if kind == "day" and trip:  # „Welchen Tag?“ – „am Donnerstag“: die offene Frage mit dem Tag
        text, kind, trip = f"{trip.text} {text}", "", None
    change = _change(services, kind, text) if kind else None
    return _respond(services, hi, service.handle_text(services, text, trip, change, chosen=chosen))


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
        if ans.trip:
            attrs["trip"] = ans.trip.to_dict()
        else:
            attrs.pop("trip", None)
        _save_trip(services, hi, attrs.get("trip"))
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
    if attrs.get("trip") or attrs.get("pending") == "transit_confirm":
        attrs.pop("trip", None)
        _save_trip(services, hi, None)
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
