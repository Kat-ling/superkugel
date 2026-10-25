"""Gesprächs-Handler: Start, freie Rede, Wiederholen, Hilfe, Beenden."""

from __future__ import annotations

import concurrent.futures as cf
import random

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.utils import get_intent_name, is_intent_name, is_request_type
from ask_sdk_model import Response

from superkugel.audiobooks import media
from superkugel.conversation.carriers import is_chat_intent, reconstruct
from superkugel.conversation.history import History
from superkugel.conversation.llm import LlmError, LlmReply
from superkugel.conversation.prompt import (
    PLAY_TOOL,
    SEARCH_MEDIA_TOOL,
    SHOW_TOOL,
    build_instructions,
    web_search_tool,
)
from superkugel.handlers.common import (
    Services,
    end_with,
    keep_open,
    play_directive,
    session_attrs,
    slot,
    uid,
)
from superkugel.services import current_context
from superkugel.services.logs import log, metric
from superkugel.services.ops import Mode
from superkugel.services.usage import TokenUsage
from superkugel.speech.styles import personalize

_EXECUTOR = cf.ThreadPoolExecutor(max_workers=4)

THINKING = ("Moment, ich überleg kurz.", "Einen Augenblick.", "Lass mich kurz nachdenken.")


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
    s = services.settings
    audio = services.audio()
    try:
        books, progress = audio.books(), audio.progress_map(user)
    except Exception as exc:  # noqa: BLE001 - ohne Bibliothek trotzdem ratschen
        log("library_unavailable", error=type(exc).__name__)
        books, progress = [], {}
    try:
        shows = media.list_shows(services.store)
    except Exception as exc:  # noqa: BLE001
        log("shows_unavailable", error=type(exc).__name__)
        shows = []
    context = current_context.prompt_block(services.store, s)
    searches_left = services.usage.searches_left()
    tools: list[dict] = []
    if books:
        tools.append(PLAY_TOOL)
    if shows:
        tools.append(SHOW_TOOL)
    if services.params.podcast_index_credentials():
        tools.append(SEARCH_MEDIA_TOOL)
    if searches_left > 0:
        tools.append(web_search_tool(s.user_region, s.timezone))
    instructions = build_instructions(
        services.style, books, progress, address=s.address_form,
        user_name=s.user_name if s.share_name_with_ai else "",
        shows_block="\n".join(media.iter_shows_prompt(shows)), context_block=context,
        web_search=searches_left > 0 if s.web_search_enabled else None, timezone=s.timezone,
    )
    client = services.llm_factory(key)
    messages = history.as_input(text)
    future = _EXECUTOR.submit(client.complete, instructions, messages, deadline=deadline,
                              tools=tools, max_tool_calls=1 if searches_left > 0 else None)
    try:
        first_wait = min(services.settings.progressive_after_s, deadline - services.clock())
        return future.result(timeout=max(0.0, first_wait))
    except cf.TimeoutError:
        if deadline - services.clock() <= 0.05:
            _book_unfinished(services, instructions, messages, searches_left > 0)
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
        _book_unfinished(services, instructions, messages, searches_left > 0)
        raise LlmError("timeout") from exc


def _book_unfinished(services: Services, instructions: str, messages: list[dict[str, str]], search: bool) -> None:
    """Abgebrochene Anfrage läuft bei OpenAI weiter und wird bezahlt. Lambda friert nach der Antwort ein,
    ein späteres Nachzählen ist unzuverlässig → sofort vorsichtig (eher zu hoch) buchen, inkl. möglicher Suche."""
    chars = len(instructions) + sum(len(m.get("content", "")) for m in messages)
    est = TokenUsage(input_tokens=chars // 3 + (3000 if search else 0),
                     output_tokens=services.settings.max_output_tokens, search_calls=1 if search else 0)
    services.usage.record(est, 0)
    log("llm_unfinished_booked", searches=est.search_calls)


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
        log("usage_limit_reached")
        return _offer_audiobook(services, hi, services.t("limit"))
    circuit = services.circuit
    if circuit.is_open():
        log("circuit_open")
        return end_with(services, hi, services.fallback_text())

    user = uid(hi)
    s = services.settings
    history = History.from_attributes(attrs.get("history")).trimmed(s.history_max_turns, s.history_max_chars)
    deadline = started + s.request_deadline_s
    try:
        reply = _call_llm(services, hi, user, history, text, min(deadline, services.clock() + s.llm_timeout_s))
    except LlmError as exc:
        _measure_total(services, started)
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
    _measure_total(services, started)

    _privacy_check(services, reply)
    for call in reply.tool_calls:
        if call.name == "play_audiobook":
            book = services.audio().book(str(call.arguments.get("book_id", "")))
            if book and not book.book_id.startswith("pod-"):  # Modell darf nur vorhandene Bücher starten
                cmd = services.audio().start_or_resume(user, book)
                lead = reply.text or f"Gern, hier ist {book.title}."
                return (hi.response_builder.speak(services.say(lead)).add_directive(play_directive(cmd))
                        .set_should_end_session(True).response)
            log("tool_unknown_book")
        elif call.name == "play_show":
            from superkugel.handlers import media as media_handlers

            show_id = str(call.arguments.get("show_id", ""))
            try:
                show = next((x for x in media.list_shows(services.store) if x.show_id == show_id), None)
            except Exception as exc:  # noqa: BLE001
                log("shows_unavailable", error=type(exc).__name__)
                show = None
            if show:
                return media_handlers.play_show(services, hi, show)
            log("tool_unknown_show")
        elif call.name == "search_media":
            from superkugel.handlers import media as media_handlers

            # Restbudget beachten: nach einer langen KI-Antwort nicht noch Sekunden suchen (Alexa-Limit 8 s)
            return media_handlers.search_media(services, hi, str(call.arguments.get("query", "")),
                                               deadline=deadline)

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
    # Keine Nachfrage: Alexa hört still weiter zu (Folgefrage ohne „Alexa“ möglich) und beendet dann leise.
    return keep_open(services, hi, answer, None)


def _measure_total(services: Services, started: float) -> None:
    """„Langsam“ = Zeit seit Eingang der Anfrage (inkl. Kaltstart, Datenbank, Zwischenmeldung, Zeitüberschreitung)."""
    if (services.clock() - started) * 1000 > services.settings.slow_answer_ms:
        metric("SlowAnswer", 1)


def _privacy_check(services: Services, reply: LlmReply) -> None:
    """Warnt (Metrik, ohne Inhalt), wenn eine Websuche den Vornamen der Nutzerin enthielt."""
    name = services.settings.user_name.strip().lower()
    if name and any(name in q.lower() for q in reply.search_queries):
        metric("SearchQueryContainedName", 1)
        log("privacy_search_contains_name")


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
    if session_attrs(hi).get("pending") == "choose_media":
        # „die erste“ kann bei ChatDieIntent landen → zuerst als Auswahl versuchen
        from superkugel.handlers import media as media_handlers

        chosen = media_handlers.choose_hit(services, hi, text)
        if chosen is not None:
            return chosen
    session_attrs(hi).pop("pending", None)
    return handle_chat_text(services, hi, text, started)


def handle_yes(services: Services, hi: HandlerInput, started: float) -> Response:
    attrs = session_attrs(hi)
    pending = attrs.pop("pending", None)
    if pending == "choose_media":
        attrs["pending"] = pending  # „ja“ ist keine Auswahl → weiter auf Nummer warten
        return keep_open(services, hi, services.t("search_choose"), services.t("search_choose"))
    if pending == "resume_book":
        from superkugel.handlers.audio import resume_current

        return resume_current(services, hi)
    if pending == "list_books":
        from superkugel.handlers.audio import list_books

        return list_books(services, hi)
    return handle_chat_text(services, hi, "ja", started)


def handle_no(services: Services, hi: HandlerInput, started: float) -> Response:
    attrs = session_attrs(hi)
    pending = attrs.pop("pending", None)
    if pending == "choose_media":
        attrs.pop("media_hits", None)  # „nein“ bei der Auswahl = abbrechen
        return keep_open(services, hi, services.t("search_cancelled"), None)
    if pending in ("resume_book", "list_books"):
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
    return (hi.response_builder.speak(services.say(last, slow=True)).set_should_end_session(False).response)


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
