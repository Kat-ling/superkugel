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
    FAHRPLAN_TOOL,
    NEWS_TOOL,
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
    session_attrs,
    slot,
    uid,
)
from superkugel.services import current_context
from superkugel.services import news as news_pool
from superkugel.services.logs import log, metric
from superkugel.services.ops import Mode
from superkugel.services.usage import TokenUsage
from superkugel.speech.styles import personalize

_EXECUTOR = cf.ThreadPoolExecutor(max_workers=4)

NEWS_SEARCH_MIN_S = 3.5  # darunter reicht die Zeit bis zum Alexa-Limit nicht mehr für eine Websuche
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
    services.count("sessions")
    # Wiederaufnahme eines kurz zuvor unterbrochenen Gesprächs
    try:
        snap = services.store.get_conversation(user) if services.settings.resume_window_s > 0 else None
    except Exception:  # noqa: BLE001
        snap = None
    resumed = bool(snap and snap.get("turns"))
    from superkugel.handlers import transit

    transit.restore_trip(services, hi, snap or {})
    if resumed:
        attrs["history"] = snap["turns"]
        greeting = services.t("welcome_back")
    elif (briefing := _morning_briefing(services, user)) is not None:
        greeting = briefing
    try:
        current = services.audio().current_book(user)
    except Exception:  # noqa: BLE001
        current = None
    if mode is Mode.AUDIOBOOKS_ONLY:
        lead = f"{greeting} " if greeting.startswith("Guten Morgen") else ""
        if current:
            attrs["pending"] = "resume_book"
            return keep_open(services, hi, lead + services.t("ai_off") + " " + services.t("resume_q"),
                             services.t("resume_q"))
        return keep_open(services, hi, lead + services.t("ai_off"), services.t("ai_off"))
    if current and not resumed:
        attrs["pending"] = "resume_book"
        question = services.t("choose")
        return keep_open(services, hi, f"{greeting} {question}", question)
    return keep_open(services, hi, greeting, services.t("ask_topic"))


def _morning_briefing(services: Services, user: str) -> str | None:
    """Morgengruß beim ersten Öffnen des Tages (5–11 Uhr) – ohne KI, nur aus gespeicherten Daten."""
    from superkugel.features import morning
    from superkugel.services.usage import local_now

    now = services.now()
    local = local_now(services.settings, now)
    if not morning.should_greet(services.store, services.settings, user, local):
        return None
    try:
        ctx = services.store.get_item("CONTEXT", "CURRENT")
    except Exception as exc:  # noqa: BLE001
        log("context_read_failed", error=type(exc).__name__)
        ctx = None
    services.count("morning")
    return morning.compose(services.t, services.settings, ctx, local, now.timestamp(), services.settings.user_name)


def _call_llm(services: Services, hi: HandlerInput, user: str, history: History, text: str,
              deadline: float, search_only: bool = False) -> LlmReply:
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
    tools.extend((FAHRPLAN_TOOL, NEWS_TOOL))
    if search_only:
        tools = []
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


def _read_news(services: Services, hi: HandlerInput, user: str, history: History, args: dict,
                deadline: float) -> str:
    """Werkzeug ``nachrichten``: Der Code wählt und liest vor. Nur ein Wunsch ohne Treffer braucht die Websuche."""
    s = services.settings
    wish = " ".join(str(args.get(k) or "").strip() for k in ("ort", "thema")).strip()
    now = services.now().timestamp()
    told = news_pool.told_ids(services.store, user)
    items = news_pool.select(news_pool.load_pool(services.store), told, wish,
                             (*s.news_interests, *([s.user_city] if s.user_city else [])), now, s.user_region)
    log("news_answer", picked=len(items), wish=bool(wish))
    if items:
        news_pool.remember_told(services.store, user, told, items)
        return f"{services.t('news_intro')} {news_pool.spoken(items)}"
    if not wish:
        return services.t("news_no_more")
    if services.usage.searches_left() <= 0 or deadline - services.clock() < NEWS_SEARCH_MIN_S:
        return services.t("news_nothing")
    try:
        reply = _call_llm(services, hi, user, history,
                          f"Such aktuelle Nachrichten zu: {wish}. Sag das Wichtigste in zwei bis drei kurzen Sätzen.",
                          deadline, search_only=True)
    except LlmError as exc:
        log("llm_error", kind=exc.kind, status=exc.status)
        return services.t("news_nothing")
    services.usage.record(reply.usage, reply.latency_ms)
    return reply.text or services.t("news_nothing")


def handle_chat_text(services: Services, hi: HandlerInput, text: str, started: float,
                     explicit_play: bool = False) -> Response:
    mode = services.params.mode()
    if mode is Mode.MAINTENANCE:
        return end_with(services, hi, services.t("maintenance"))
    attrs = session_attrs(hi)
    from superkugel.handlers import transit
    from superkugel.transit import service as transit_service
    from superkugel.transit.ask import looks_like_transit, travel_dest

    if hi.request_envelope.session and hi.request_envelope.session.new:
        transit.restore_trip(services, hi)  # Frage öffnet die Sitzung direkt: Reise von vorhin gilt weiter
    if text.strip() and (transit.is_follow_up(hi, text) or looks_like_transit(text)
                         or transit.is_new_target(services, hi, text)):
        return transit.answer_text(services, hi, text)  # Fahrplan: ohne KI, auch im Hörbuch-Modus
    # „ich möchte morgen nach Bergdorf fahren“: nur wenn das Ziel eine bekannte Haltestelle ist, sonst KI
    if text.strip() and (dest := travel_dest(text)) and transit_service.knows_place(services, dest):
        return transit.answer_text(services, hi, text)
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
    attrs.pop("trip", None)  # Thema gewechselt: „danach“ gehört jetzt zum Gespräch
    circuit.record_success()
    services.usage.record(reply.usage, reply.latency_ms)
    _measure_total(services, started)

    _privacy_check(services, reply)
    spoken = ""
    for call in reply.tool_calls:
        if call.name == "play_audiobook":
            book = services.audio().book(str(call.arguments.get("book_id", "")))
            if book and not book.book_id.startswith("pod-"):  # Modell darf nur vorhandene Bücher starten
                from superkugel.handlers import audio

                return audio.from_ai(services, hi, book, text, reply.text or f"Gern, hier ist {book.title}.",
                                     explicit_play)
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
        elif call.name == "nachrichten":
            spoken = _read_news(services, hi, user, history, call.arguments, deadline)
            break
        elif call.name == "fahrplan":
            from superkugel.handlers import transit

            return transit.from_tool(services, hi, call.arguments, text)  # Zeiten rechnet der Code, nie die KI
        elif call.name == "search_media":
            from superkugel.handlers import media as media_handlers

            # Restbudget beachten: nach einer langen KI-Antwort nicht noch Sekunden suchen (Alexa-Limit 8 s)
            return media_handlers.search_media(services, hi, str(call.arguments.get("query", "")),
                                               deadline=deadline)

    answer = spoken or reply.text or services.t("not_understood")
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
        services.count("slow")


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
    if session_attrs(hi).get("pending") == "transit_confirm":
        # Antwort auf „Meinst du …?“: „ja genau“, „nein“ oder gleich der richtige Ort („in Tirol“)
        from superkugel.handlers import transit

        answered = transit.confirm_text(services, hi, text)
        if answered is not None:
            return answered
    from superkugel.audiobooks import matching
    from superkugel.handlers import audio

    pending = session_attrs(hi).get("pending")
    if pending in ("restart_book", "play_book"):
        answer = audio.restart_answer if pending == "restart_book" else audio.play_answer
        answered = answer(services, hi, text)
        if answered is not None:
            return answered
    session_attrs(hi).pop("pending", None)
    wish = matching.restart_wish(text)
    if wish is not None and matching.mentions_book(text):
        return audio.restart(services, hi, wish)
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
    if pending == "transit_confirm":
        from superkugel.handlers import transit

        return transit.confirm_yes(services, hi)
    if pending == "restart_book":
        from superkugel.handlers.audio import restart_yes

        return restart_yes(services, hi)
    if pending == "play_book":
        from superkugel.handlers.audio import play_yes

        return play_yes(services, hi)
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
    if pending == "transit_confirm":
        from superkugel.handlers import transit

        return transit.confirm_no(services, hi)
    if pending == "restart_book":
        from superkugel.handlers.audio import restart_no

        return restart_no(services, hi)
    if pending == "play_book":
        from superkugel.handlers.audio import play_no

        return play_no(services, hi)
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
    # Bewusstes Beenden: nächstes Öffnen startet frisch (kein „Wo waren wir?“), nur die Reise bleibt kurz gemerkt.
    from superkugel.handlers import transit

    try:
        transit.end_session_keep_trip(services, hi)
    except Exception as exc:  # noqa: BLE001
        log("conversation_delete_failed", error=type(exc).__name__)
    return end_with(services, hi, personalize(services.style.goodbye[services.settings.address_form],
                                               services.settings.user_name))


def handle_forget(services: Services, hi: HandlerInput) -> Response:
    session_attrs(hi)["history"] = []
    session_attrs(hi).pop("trip", None)
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
