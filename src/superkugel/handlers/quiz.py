"""Rätsel & Gedächtnistraining: geduldig, ohne Druck, ohne KI (nur „Erklär mir das“ fragt die KI)."""

from __future__ import annotations

import random

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from superkugel.handlers.common import Services, keep_open, session_attrs, uid
from superkugel.quiz import engine
from superkugel.quiz.items import Item
from superkugel.services.logs import log
from superkugel.services.usage import local_now

MAX_PER_SESSION = 10
FLAG_TTL_S = 2 * 86400


def _today(services: Services) -> str:
    return local_now(services.settings, services.now()).date().isoformat()


def _seen(services: Services, hi: HandlerInput) -> dict[str, str]:
    try:
        return dict((services.store.get_item(f"USER#{uid(hi)}", "QUIZSEEN") or {}).get("seen") or {})
    except Exception as exc:  # noqa: BLE001
        log("quiz_seen_failed", error=type(exc).__name__)
        return {}


def _mark(services: Services, hi: HandlerInput, item: Item) -> None:
    today = local_now(services.settings, services.now()).date()
    seen = engine.prune(_seen(services, hi), today)
    seen[item.item_id] = today.isoformat()
    try:
        services.store.put_item(f"USER#{uid(hi)}", "QUIZSEEN", {"seen": seen}, ttl_s=engine.SEEN_TTL_S)
    except Exception as exc:  # noqa: BLE001
        log("quiz_seen_failed", error=type(exc).__name__)


def _right_today(services: Services, hi: HandlerInput, add: int = 0) -> int:
    today = _today(services)
    try:
        flags = services.store.get_item(f"USER#{uid(hi)}", "DAYFLAGS") or {}
        if flags.get("date") != today:
            flags = {"date": today}
        count = int(flags.get("quiz_right", 0)) + add
        if add:
            services.store.put_item(f"USER#{uid(hi)}", "DAYFLAGS", {**flags, "quiz_right": count}, ttl_s=FLAG_TTL_S)
        return count
    except Exception as exc:  # noqa: BLE001
        log("quiz_flags_failed", error=type(exc).__name__)
        return 0


def _ask(services: Services, hi: HandlerInput, lead: str, last_kind: str | None, asked: int) -> Response:
    today = local_now(services.settings, services.now()).date()
    item = engine.pick(_seen(services, hi), today, last_kind, random.Random())
    attrs = session_attrs(hi)
    if item is None:
        attrs.pop("pending", None)
        attrs.pop("quiz", None)
        return keep_open(services, hi, f"{lead} {services.t('quiz_empty')}".strip(), None)
    _mark(services, hi, item)
    attrs["pending"] = "quiz"
    attrs["quiz"] = {"id": item.item_id, "tries": 0, "asked": asked + 1, "kind": item.kind}
    return keep_open(services, hi, f"{lead} {item.question}".strip(), services.t("quiz_say_answer"))


def start(services: Services, hi: HandlerInput) -> Response:
    services.count("quiz")
    log("quiz_start")
    return _ask(services, hi, services.t("quiz_intro"), None, 0)


def _next(services: Services, hi: HandlerInput, lead: str) -> Response:
    state = session_attrs(hi).get("quiz") or {}
    asked = int(state.get("asked", 0))
    if asked >= MAX_PER_SESSION:
        return finish(services, hi, lead)
    return _ask(services, hi, f"{lead} {services.t('quiz_next')}", state.get("kind"), asked)


def finish(services: Services, hi: HandlerInput, lead: str = "") -> Response:
    attrs = session_attrs(hi)
    attrs.pop("pending", None)
    attrs.pop("quiz", None)
    right = _right_today(services, hi)
    closing = services.t("quiz_end", count=right) if right > 0 else services.t("quiz_end_plain")
    return keep_open(services, hi, f"{lead} {closing}".strip(), None)  # danach still weiter zuhören


def current_item(hi: HandlerInput) -> Item | None:
    from superkugel.handlers.common import has_session

    if not has_session(hi):
        return None
    attrs = session_attrs(hi)
    if attrs.get("pending") != "quiz":
        return None
    return engine.item((attrs.get("quiz") or {}).get("id"))


def answer(services: Services, hi: HandlerInput, text: str, started: float | None = None) -> Response | None:
    """Antwort während eines Rätsels. None = kein Rätsel aktiv."""
    item = current_item(hi)
    if item is None:
        return None
    state = session_attrs(hi)["quiz"]
    if engine.wants_explanation(text) and started is not None:
        from superkugel.handlers.conversation import handle_chat_text

        session_attrs(hi).pop("pending", None)
        question = f"Erklär mir bitte kurz und freundlich: {item.question} Die Antwort ist: {item.spoken_solution}."
        return handle_chat_text(services, hi, question, started)
    if engine.gives_up(text):
        return _next(services, hi, services.t("quiz_solution", answer=item.spoken_solution))
    if engine.is_correct(item, text):
        _right_today(services, hi, add=1)
        praise = services.t(random.choice(("quiz_right_1", "quiz_right_2", "quiz_right_3")))
        return _next(services, hi, praise)
    state["tries"] = int(state.get("tries", 0)) + 1
    if state["tries"] < 2:
        q = services.t("quiz_again", hint=item.hint)
        return keep_open(services, hi, q, services.t("quiz_say_answer"))
    return _next(services, hi, services.t("quiz_solution", answer=item.spoken_solution))


def answer_intent(services: Services, hi: HandlerInput, started: float) -> Response:
    """QuizAnswerIntent ({answer}). Ohne Rätsel: laufender Erinnerungsdialog oder Gespräch."""
    from superkugel.handlers.common import slot
    from superkugel.handlers.conversation import route_pending

    text = slot(hi, "answer")
    resp = route_pending(services, hi, text, started)
    if resp is not None:
        return resp
    # Ohne Dialog: kein Sammelbecken für Hintergrundgeräusche → wie bisher „nicht verstanden“
    from superkugel.handlers.conversation import handle_fallback

    return handle_fallback(services, hi)
