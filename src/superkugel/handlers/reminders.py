"""Erinnerungen: anlegen (immer mit Bestätigung), auflisten, löschen.

Der Erinnerungstext geht nur an Amazon (dort wird die Erinnerung ohnehin gespeichert) – nicht in DynamoDB,
nicht in Logs, nicht an OpenAI. Zwischenstände liegen nur in den Sitzungsattributen der laufenden Sitzung.
"""

from __future__ import annotations

import datetime as dt
import re

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.ui import AskForPermissionsConsentCard

from superkugel.handlers.common import Services, end_with, keep_open, session_attrs, slot, uid
from superkugel.language import fold
from superkugel.reminders import parse
from superkugel.reminders.api import PERMISSION, ReminderApi, ReminderError, urllib_transport
from superkugel.reminders.parse import Draft
from superkugel.services.logs import log, metric

PENDING = ("reminder_text", "reminder_time", "reminder_confirm", "reminder_delete_choose", "reminder_delete_confirm")
_REPEAT = re.compile(r"\b(jeden|jede|jedes|täglich|taeglich|wöchentlich|immer wieder|alle zwei)\b")
_YES = {"ja", "jo", "passt", "genau", "gern", "gerne", "richtig", "stimmt", "okay", "ok", "bitte", "jawohl",
        "freilich", "sicher", "klar", "eh"}
_YES_AFTER_NA = {"klar", "freilich", "sicher", "eh", "passt", "ja", "genau", "logisch"}
_NO = {"nein", "nö", "na", "nee", "falsch", "abbrechen"}
_LIST_MAX = 5
OWN_TTL_S = 400 * 86400  # Kennungen eigener Erinnerungen (ohne Text) – Erinnerungen liegen max. ~1 Jahr voraus


def _own_tokens(services: Services, hi: HandlerInput) -> set[str]:
    """alertTokens, die DIESES Gerät angelegt hat. Die API arbeitet pro Konto+Skill – über das gemeinsame
    Admin-Konto sähe sie sonst auch Erinnerungen, die der Admin an seinem Echo angelegt hat."""
    try:
        return set((services.store.get_item(f"USER#{uid(hi)}", "REMINDERS") or {}).get("tokens") or [])
    except Exception as exc:  # noqa: BLE001
        log("reminder_tokens_failed", error=type(exc).__name__)
        return set()


def _save_tokens(services: Services, hi: HandlerInput, tokens: set[str]) -> None:
    try:
        services.store.put_item(f"USER#{uid(hi)}", "REMINDERS", {"tokens": sorted(tokens)[-200:]}, ttl_s=OWN_TTL_S)
    except Exception as exc:  # noqa: BLE001
        log("reminder_tokens_failed", error=type(exc).__name__)


def _api(services: Services, hi: HandlerInput) -> ReminderApi:
    system = hi.request_envelope.context.system
    return ReminderApi(getattr(system, "api_endpoint", "") or "", getattr(system, "api_access_token", "") or "",
                       services.settings.timezone, transport=services.reminder_transport or urllib_transport)


def _permission_denied(hi: HandlerInput) -> bool:
    """True nur, wenn Alexa ausdrücklich meldet, dass die Berechtigung fehlt (sonst probiert die API es)."""
    user = getattr(hi.request_envelope.context.system, "user", None)
    perms = getattr(user, "permissions", None)
    scopes = getattr(perms, "scopes", None) or {}
    scope = scopes.get(PERMISSION) if isinstance(scopes, dict) else None
    status = str(getattr(scope, "status", "") or "")
    return bool(scope) and not status.upper().endswith("GRANTED")


def _ask_permission(services: Services, hi: HandlerInput) -> Response:
    _clear(hi)
    hi.response_builder.set_card(AskForPermissionsConsentCard(permissions=[PERMISSION]))
    return end_with(services, hi, services.t("reminder_permission"))


def _clear(hi: HandlerInput) -> None:
    attrs = session_attrs(hi)
    for key in ("reminder", "reminder_tries", "reminder_list"):
        attrs.pop(key, None)
    if attrs.get("pending") in PENDING:
        attrs.pop("pending", None)


def _api_error(services: Services, hi: HandlerInput, exc: ReminderError) -> Response:
    log("reminder_api_error", kind=exc.kind, status=exc.status)
    if exc.kind == "permission":
        return _ask_permission(services, hi)
    _clear(hi)
    if exc.kind == "limit":
        return end_with(services, hi, services.t("reminder_limit"))
    if exc.kind == "unsupported":
        return end_with(services, hi, services.t("reminder_unsupported"))
    metric("ReminderApiError", 1)
    services.count("reminder_errors")
    return end_with(services, hi, services.t("reminder_failed"))


# ------------------------------------------------------------------ Anlegen
def start_free(services: Services, hi: HandlerInput) -> Response:
    """„Erinner mich morgen um zehn an den Arzt“ (Freitext-Intent)."""
    return start_text(services, hi, slot(hi, "query"))


def start_text(services: Services, hi: HandlerInput, raw: str) -> Response:
    """Auch für das KI-Werkzeug ``set_reminder``: ausgewertet wird immer ihr eigener Satz."""
    if _REPEAT.search(fold(raw)):
        _clear(hi)
        return keep_open(services, hi, services.t("reminder_repeat"), None)
    draft = parse.parse(raw, services.now(), services.settings.timezone)
    session_attrs(hi).pop("reminder_tries", None)
    return _continue(services, hi, draft)


def answer_time(services: Services, hi: HandlerInput) -> Response:
    """ReminderTimeIntent („um acht“, „am Sonntag“, „in einer Stunde“): nur als Antwort im Erinnerungsdialog.
    Ohne Dialog ist das kein Erinnerungswunsch (keine ungefragte Nachfrage) → wie bisher „nicht verstanden“."""
    if session_attrs(hi).get("pending") in PENDING[:3]:
        return start_slots(services, hi)
    from superkugel.handlers.conversation import handle_fallback

    return handle_fallback(services, hi)


def start_slots(services: Services, hi: HandlerInput) -> Response:
    """SetReminderIntent („Erinnerung für morgen um acht“) mit AMAZON.DATE / AMAZON.TIME / AMAZON.DURATION."""
    new = parse.from_slots(slot(hi, "date"), slot(hi, "time"), slot(hi, "duration"), services.now(),
                           services.settings.timezone)
    attrs = session_attrs(hi)
    old = Draft.from_attrs(attrs.get("reminder")) if attrs.get("pending") in PENDING[:3] else Draft()
    return _continue(services, hi, old.merge(new))


def _continue(services: Services, hi: HandlerInput, draft: Draft) -> Response:
    attrs = session_attrs(hi)
    if _permission_denied(hi):
        return _ask_permission(services, hi)
    attrs["reminder"] = draft.to_attrs()
    if not draft.text:
        attrs["pending"] = "reminder_text"
        return keep_open(services, hi, services.t("reminder_what"), services.t("reminder_what"))
    resolved = parse.resolve(draft, services.now(), services.settings.timezone)
    if resolved is None:
        attrs["pending"] = "reminder_time"
        return keep_open(services, hi, services.t("reminder_when"), services.t("reminder_when"))
    if resolved.in_past:
        attrs["reminder"] = Draft(text=draft.text).to_attrs()
        attrs["pending"] = "reminder_time"
        return keep_open(services, hi, services.t("reminder_past"), services.t("reminder_when"))
    attrs["pending"] = "reminder_confirm"
    when = parse.spoken_when(resolved.when, services.now())
    return keep_open(services, hi, services.t("reminder_confirm", when=when, what=draft.text),
                     services.t("reminder_confirm_q"))


def confirm(services: Services, hi: HandlerInput) -> Response:
    attrs = session_attrs(hi)
    draft = Draft.from_attrs(attrs.get("reminder"))
    now = services.now()
    resolved = parse.resolve(draft, now, services.settings.timezone)
    if resolved is None or not draft.text:
        return _continue(services, hi, draft)
    if resolved.in_past:  # beim Zögern über die Uhrzeit hinaus
        return _continue(services, hi, draft)
    try:
        token = _api(services, hi).create(resolved.when, draft.text, now)
    except ReminderError as exc:
        return _api_error(services, hi, exc)
    if token:
        _save_tokens(services, hi, _own_tokens(services, hi) | {token})
    _clear(hi)
    services.count("reminder")
    log("reminder_created")
    return keep_open(services, hi, services.t("reminder_done", when=parse.spoken_when(resolved.when, now)), None)


def cancel(services: Services, hi: HandlerInput) -> Response:
    _clear(hi)
    return keep_open(services, hi, services.t("reminder_cancelled"), None)


def _yes_no(text: str) -> bool | None:
    """Kärntnerisch tolerant: „na klar“/„na freilich“ = ja, „na“ allein oder „na, lieber nicht“ = nein."""
    words = [w.strip(".,!") for w in fold(text).split()]
    if not words:
        return None
    first = words[0]
    if first == "na" and len(words) > 1 and words[1] in _YES_AFTER_NA:
        return True
    if first in _YES:
        return not (len(words) > 1 and words[1] in ("nicht", "nein"))
    if first in _NO or words[:2] in (["lieber", "nicht"], ["doch", "nicht"]):
        return False
    return None


def _bare_hour(text: str) -> str | None:
    """„zehn“ / „10“ als Antwort auf „Wann?“ (kommt oft über ChooseResultIntent als Zahl)."""
    words = [w for w in fold(text).split() if w not in ("um", "uhr", "so", "gegen")]
    if len(words) == 1:
        from superkugel.language import word_to_int

        n = word_to_int(words[0])
        if n is not None and 0 <= n <= 24:
            return f"{n % 24:02d}:00"
    return None


def continue_text(services: Services, hi: HandlerInput, text: str) -> Response | None:
    """Freie Antwort während eines Erinnerungs-Dialogs. None = gehört nicht dazu (normal weiter)."""
    attrs = session_attrs(hi)
    pending = attrs.get("pending")
    if pending not in PENDING:
        return None
    draft = Draft.from_attrs(attrs.get("reminder"))
    if pending in ("reminder_confirm", "reminder_delete_confirm"):
        answer = _yes_no(text)
        if pending == "reminder_delete_confirm":
            if answer is None:
                return None
            return delete_confirmed(services, hi) if answer else cancel(services, hi)
        new = parse.parse(text, services.now(), services.settings.timezone)
        if new.time or new.date:  # „nein, um elf“ / „ja, aber um elf“ → korrigieren und nochmal bestätigen
            new.text = None
            return _continue(services, hi, draft.merge(new))
        if answer is True:
            return confirm(services, hi)
        if answer is False:
            return cancel(services, hi)
        return None
    if pending == "reminder_delete_choose":
        return choose(services, hi, text)
    new = parse.parse(text, services.now(), services.settings.timezone)
    if pending == "reminder_text":
        if not new.text:
            new.text = text.strip()[: parse.MAX_TEXT] or None
        return _continue(services, hi, draft.merge(new))
    # reminder_time: Text ohne Uhrzeit → einmal nachfragen, dann freundlich aufgeben
    if not new.time and (hour := _bare_hour(text)):
        new.time = hour
    merged = draft.merge(Draft(date=new.date, time=new.time, pm_hint=new.pm_hint))
    if not merged.time:
        return retry_or_give_up(services, hi)
    return _continue(services, hi, merged)


def retry_or_give_up(services: Services, hi: HandlerInput) -> Response:
    """Unverständliche Antwort im Erinnerungsdialog: einmal nachfragen, dann freundlich aufgeben (keine Schleife)."""
    attrs = session_attrs(hi)
    tries = int(attrs.get("reminder_tries", 0)) + 1
    attrs["reminder_tries"] = tries
    if tries >= 2:
        _clear(hi)
        return keep_open(services, hi, services.t("not_understood"), None)
    key = {"reminder_text": "reminder_what", "reminder_time": "reminder_when"}.get(str(attrs.get("pending")),
                                                                                  "reminder_confirm_q")
    return keep_open(services, hi, services.t(key), services.t(key))


# ------------------------------------------------------------------ Auflisten / Löschen
def _spoken_list(services: Services, items: list[dict]) -> str:
    now = services.now()
    parts = []
    for i, r in enumerate(items):
        when = parse.spoken_when(dt.datetime.fromisoformat(r["when"]), now) if r.get("when") else ""
        parts.append(f"{i + 1}. {when} an {r['text']}".replace("  ", " "))
    return "; ".join(parts)


def _load(services: Services, hi: HandlerInput) -> list[dict] | Response:
    if _permission_denied(hi):
        return _ask_permission(services, hi)
    try:
        reminders = _api(services, hi).list()
    except ReminderError as exc:
        return _api_error(services, hi, exc)
    now = services.now()
    own = _own_tokens(services, hi)
    upcoming = [r for r in reminders if r.token in own and (r.when is None or r.when > now)]
    return [{"token": r.token, "when": r.when.isoformat() if r.when else "", "text": r.text} for r in upcoming]


def list_reminders(services: Services, hi: HandlerInput) -> Response:
    items = _load(services, hi)
    if not isinstance(items, list):
        return items
    if not items:
        return keep_open(services, hi, services.t("reminder_none"), None)
    speech = services.t("reminder_list", listing=_spoken_list(services, items[:_LIST_MAX]))
    if len(items) > _LIST_MAX:
        speech += " " + services.t("reminder_list_more", count=len(items) - _LIST_MAX)
    return keep_open(services, hi, speech, None)


def delete_start(services: Services, hi: HandlerInput) -> Response:
    items = _load(services, hi)
    if not isinstance(items, list):
        return items
    if not items:
        return keep_open(services, hi, services.t("reminder_none"), None)
    attrs = session_attrs(hi)
    attrs["reminder_list"] = items[:_LIST_MAX]
    if len(items) == 1:
        return _ask_delete(services, hi, 0)
    attrs["pending"] = "reminder_delete_choose"
    speech = services.t("reminder_list", listing=_spoken_list(services, items[:_LIST_MAX]))
    return keep_open(services, hi, f"{speech} {services.t('reminder_delete_which')}", services.t("reminder_delete_which"))


def _ask_delete(services: Services, hi: HandlerInput, idx: int) -> Response:
    attrs = session_attrs(hi)
    item = attrs["reminder_list"][idx]
    attrs["reminder_list"] = [item]
    attrs["pending"] = "reminder_delete_confirm"
    when = parse.spoken_when(dt.datetime.fromisoformat(item["when"]), services.now()) if item.get("when") else ""
    q = services.t("reminder_delete_confirm", when=when, what=item["text"]).replace("  ", " ")
    return keep_open(services, hi, q, q)


def choose(services: Services, hi: HandlerInput, choice: str) -> Response | None:
    """„die zweite“ / „Nummer 2“ / „2“ in der Löschauswahl. None = keine Auswahl erkannt."""
    from superkugel.handlers.media import ORDINALS

    items = session_attrs(hi).get("reminder_list") or []
    words = [w for w in fold(choice).split() if w not in ("die", "das", "nummer", "bitte", "lösch", "lösche")]
    idx = None
    if len(words) == 1:
        idx = len(items) if words[0] in ("letzte", "letzten") else ORDINALS.get(words[0])
        if idx is None:
            idx = parse.ordinal_to_int(words[0])
    if not idx or not 1 <= idx <= len(items):
        return None
    return _ask_delete(services, hi, idx - 1)


def delete_confirmed(services: Services, hi: HandlerInput) -> Response:
    items = session_attrs(hi).get("reminder_list") or []
    if not items:
        _clear(hi)
        return keep_open(services, hi, services.t("reminder_cancelled"), None)
    try:
        _api(services, hi).delete(items[0]["token"])
    except ReminderError as exc:
        return _api_error(services, hi, exc)
    _save_tokens(services, hi, _own_tokens(services, hi) - {items[0]["token"]})
    _clear(hi)
    log("reminder_deleted")
    return keep_open(services, hi, services.t("reminder_deleted"), None)
