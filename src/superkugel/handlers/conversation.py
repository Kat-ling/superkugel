"""Gesprächs-Handler: Start, freie Rede, Wiederholen, Hilfe, Beenden."""

from __future__ import annotations

import concurrent.futures as cf
import random

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.utils import get_intent_name, is_intent_name, is_request_type
from ask_sdk_model import Response

from superkugel.conversation.carriers import is_chat_intent, reconstruct
from superkugel.conversation.history import History
from superkugel.conversation.llm import LlmError, LlmReply
from superkugel.conversation.prompt import PLAY_TOOL, build_instructions
from superkugel.handlers.common import (
    Services,
    end_with,
    keep_open,
    play_directive,
    session_attrs,
    slot,
    uid,
)
from superkugel.services.logs import log, metric
from superkugel.services.ops import Mode
from superkugel.speech.styles import personalize

_EXECUTOR = cf.ThreadPoolExecutor(max_workers=2)

THINKING = ("Moment, ich überleg kurz.", "Einen Augenblick.", "Lass mich kurz nachdenken.")
REPROMPTS = ("Magst du noch was wissen?", "Noch etwas?", "Was meinst du dazu?")
REPROMPTS_SIE = ("Möchten Sie noch etwas wissen?", "Noch etwas?", "Was meinen Sie dazu?")


def _reprompt(services: Services) -> str:
    return random.choice(REPROMPTS if services.settings.address_form == "du" else REPROMPTS_SIE)


def handle_launch(services: Services, hi: HandlerInput) -> Response:
    mode = services.params.mode()
    if mode is Mode.MAINTENANCE:
        return end_with(services, hi, services.t("maintenance"))
    user = uid(hi)
    attrs = session_attrs(hi)
    style = services.style
    form = services.settings.address_form
    greeting = personalize(style.greeting[form], services.settings.user_name)
    # Wiederaufnahme eines kurz zuvor unterbrochenen Gesprächs
    try:
        snap = services.store.get_conversation(user) if services.settings.resume_window_s > 0 else None
    except Exception:  # noqa: BLE001
        snap = None
    resumed = bool(snap and snap.get("turns"))
    if resumed:
        attrs["history"] = snap["turns"]
        greeting = services.t("welcome_back")
    try:
        current = services.audio().current_book(user)
    except Exception:  # noqa: BLE001
        current = None
    if mode is Mode.AUDIOBOOKS_ONLY:
        if current:
            attrs["pending"] = "resume_book"
            return keep_open(services, hi, services.t("ai_off") + " " + services.t("resume_q"), services.t("resume_q"))
        return keep_open(services, hi, services.t("ai_off"), services.t("ai_off"))
    if current and not resumed:
        attrs["pending"] = "resume_book"
        question = services.t("choose")
        return keep_open(services, hi, f"{greeting} {question}", question)
    return keep_open(services, hi, greeting, services.t("ask_topic"))


def _call_llm(services: Services, hi: HandlerInput, user: str, history: History, text: str,
              deadline: float) -> LlmReply:
    key = services.params.openai_api_key()
    if not key:
        raise LlmError("no_key")
    audio = services.audio()
    try:
        books, progress = audio.books(), audio.progress_map(user)
    except Exception as exc:  # noqa: BLE001 - ohne Bibliothek trotzdem plaudern
        log("library_unavailable", error=type(exc).__name__)
        books, progress = [], {}
    instructions = build_instructions(services.style, books, progress, address=services.settings.address_form,
                                      user_name=services.settings.user_name)
    client = services.llm_factory(key)
    tools = [PLAY_TOOL] if books else None
    future = _EXECUTOR.submit(client.complete, instructions, history.as_input(text), deadline=deadline, tools=tools)
    try:
        first_wait = min(services.settings.progressive_after_s, deadline - services.clock())
        return future.result(timeout=max(0.0, first_wait))
    except cf.TimeoutError:
        if deadline - services.clock() <= 0.05:
            future.add_done_callback(lambda f: _record_late(services, f))
            raise LlmError("timeout") from None
    # Antwort dauert: kurze Zwischenmeldung, Gesamtlimit bleibt gleich (Alexa-Regel).
    try:
        services.progressive(hi, services.say(random.choice(THINKING)))
    except Exception as exc:  # noqa: BLE001 - Zwischenmeldung ist optional
        log("progressive_failed", error=type(exc).__name__)
    remaining = deadline - services.clock()
    try:
        return future.result(timeout=max(0.1, remaining))
    except cf.TimeoutError as exc:
        # Die Anfrage läuft weiter und wird bezahlt → Verbrauch nachträglich zählen.
        future.add_done_callback(lambda f: _record_late(services, f))
        raise LlmError("timeout") from exc


def _record_late(services: Services, future: cf.Future) -> None:
    try:
        reply = future.result()
    except Exception:  # noqa: BLE001
        return
    services.usage.record(reply.usage, reply.latency_ms)


def handle_chat_text(services: Services, hi: HandlerInput, text: str, started: float) -> Response:
    mode = services.params.mode()
    if mode is Mode.MAINTENANCE:
        return end_with(services, hi, services.t("maintenance"))
    attrs = session_attrs(hi)
    if mode is Mode.AUDIOBOOKS_ONLY:
        return _offer_audiobook(services, hi, services.t("ai_off_short"))
    if not text.strip():
        return keep_open(services, hi, services.t("not_understood"), services.t("tip_short"))
    if services.usage.limit_reached():
        metric("UsageLimitReached", 1)
        return _offer_audiobook(services, hi, services.t("limit"))
    circuit = services.circuit
    if circuit.is_open():
        metric("CircuitOpen", 1)
        return end_with(services, hi, services.fallback_text())

    user = uid(hi)
    s = services.settings
    history = History.from_attributes(attrs.get("history")).trimmed(s.history_max_turns, s.history_max_chars)
    deadline = started + s.request_deadline_s
    try:
        reply = _call_llm(services, hi, user, history, text, min(deadline, services.clock() + s.llm_timeout_s))
    except LlmError as exc:
        circuit.record_failure()
        metric("LlmError", 1)
        log("llm_error", kind=exc.kind, status=exc.status)
        if exc.kind == "auth":
            services.params.invalidate_api_key()
        if exc.retryable and not attrs.get("ai_failed"):
            attrs["ai_failed"] = True
            return keep_open(services, hi, services.t("glitch"), services.t("glitch"))
        return end_with(services, hi, services.fallback_text())

    attrs["ai_failed"] = False
    attrs["misunderstood"] = 0
    circuit.record_success()
    services.usage.record(reply.usage, reply.latency_ms)

    for call in reply.tool_calls:
        if call.name == "play_audiobook":
            book = services.audio().book(str(call.arguments.get("book_id", "")))
            if book:  # Modell darf nur vorhandene Bücher starten
                cmd = services.audio().start_or_resume(user, book)
                lead = reply.text or f"Gern, hier ist {book.title}."
                return (hi.response_builder.speak(services.say(lead)).add_directive(play_directive(cmd))
                        .set_should_end_session(True).response)
            log("tool_unknown_book")

    answer = reply.text or services.t("not_understood")
    history.add("user", text)
    history.add("assistant", answer)
    history = history.trimmed(s.history_max_turns, s.history_max_chars)
    attrs["history"] = history.to_attributes()
    if s.resume_window_s > 0:
        try:
            services.store.put_conversation(user, {"turns": history.to_attributes()}, s.resume_window_s)
        except Exception as exc:  # noqa: BLE001
            log("conversation_save_failed", error=type(exc).__name__)
    return keep_open(services, hi, answer, _reprompt(services))


def _offer_audiobook(services: Services, hi: HandlerInput, lead: str) -> Response:
    """KI nicht verfügbar: Hörbuch anbieten (Sitzung bleibt offen, „ja“ kommt beim Skill an)."""
    try:
        current = services.audio().current_book(uid(hi))
    except Exception:  # noqa: BLE001
        current = None
    if not current:
        return end_with(services, hi, lead)
    session_attrs(hi)["pending"] = "resume_book"
    return keep_open(services, hi, f"{lead} {services.t('resume_q')}", services.t("resume_q"))


def handle_chat_intent(services: Services, hi: HandlerInput, started: float) -> Response:
    intent = get_intent_name(hi)
    text = reconstruct(intent, slot(hi, "query"))
    session_attrs(hi).pop("pending", None)
    return handle_chat_text(services, hi, text, started)


def handle_yes(services: Services, hi: HandlerInput, started: float) -> Response:
    attrs = session_attrs(hi)
    pending = attrs.pop("pending", None)
    if pending == "resume_book":
        from superkugel.handlers.audio import resume_current

        return resume_current(services, hi)
    if pending == "list_books":
        from superkugel.handlers.audio import list_books

        return list_books(services, hi)
    return handle_chat_text(services, hi, "ja", started)


def handle_no(services: Services, hi: HandlerInput, started: float) -> Response:
    attrs = session_attrs(hi)
    if attrs.pop("pending", None) in ("resume_book", "list_books"):
        q = services.t("no_book_then")
        return keep_open(services, hi, q, q)
    return handle_chat_text(services, hi, "nein", started)


def handle_start_chat(services: Services, hi: HandlerInput) -> Response:
    session_attrs(hi).pop("pending", None)
    q = services.t("start_chat")
    return keep_open(services, hi, q, q)


def handle_fallback(services: Services, hi: HandlerInput) -> Response:
    attrs = session_attrs(hi)
    attrs["misunderstood"] = int(attrs.get("misunderstood", 0)) + 1
    # Geduldig: erst nach mehreren Versuchen verabschieden; dazwischen Tipps statt Abbruch.
    if attrs["misunderstood"] >= services.settings.misunderstood_limit:
        return end_with(services, hi, services.t("give_up"))
    if attrs["misunderstood"] % 2 == 0:
        return keep_open(services, hi, services.t("tip"), services.t("tip_short"))
    return keep_open(services, hi, services.t("not_understood"), services.t("tip_short"))


def handle_repeat(services: Services, hi: HandlerInput) -> Response:
    last = session_attrs(hi).get("last_speech")
    if not last:
        return keep_open(services, hi, services.t("nothing_said"), services.t("ask_topic"))
    return (hi.response_builder.speak(services.say(last, slow=True)).ask(services.say(_reprompt(services)))
            .set_should_end_session(False).response)


def handle_help(services: Services, hi: HandlerInput) -> Response:
    return keep_open(services, hi, services.t("help"), services.t("help_q"))


def handle_goodbye(services: Services, hi: HandlerInput) -> Response:
    # Bewusstes Beenden: nächstes Öffnen startet frisch (kein „Wo waren wir?“).
    try:
        services.store.delete_conversation(uid(hi))
    except Exception as exc:  # noqa: BLE001
        log("conversation_delete_failed", error=type(exc).__name__)
    return end_with(services, hi, personalize(services.style.goodbye[services.settings.address_form],
                                               services.settings.user_name))


def handle_forget(services: Services, hi: HandlerInput) -> Response:
    session_attrs(hi)["history"] = []
    try:
        services.store.delete_conversation(uid(hi))
    except Exception as exc:  # noqa: BLE001
        log("conversation_delete_failed", error=type(exc).__name__)
    return keep_open(services, hi, services.t("forgotten"), services.t("ask_topic"))


def can_chat(hi: HandlerInput) -> bool:
    return is_request_type("IntentRequest")(hi) and is_chat_intent(get_intent_name(hi))


__all__ = [
    "can_chat",
    "handle_chat_intent",
    "handle_fallback",
    "handle_forget",
    "handle_goodbye",
    "handle_help",
    "handle_launch",
    "handle_no",
    "handle_repeat",
    "handle_start_chat",
    "handle_yes",
    "is_intent_name",
]
