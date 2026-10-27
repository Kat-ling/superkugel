"""Morgengruß pro Gerät ab- und wieder einschalten („Lass den Morgengruß weg“)."""

from __future__ import annotations

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from superkugel.features import morning
from superkugel.handlers.common import Services, end_with, keep_open, uid
from superkugel.services.logs import log


def _set(services: Services, hi: HandlerInput, enabled: bool) -> Response:
    try:
        morning.set_enabled(services.store, uid(hi), enabled)
    except Exception as exc:  # noqa: BLE001
        log("morning_pref_failed", error=type(exc).__name__)
        return end_with(services, hi, services.fallback_text())
    return keep_open(services, hi, services.t("morning_on" if enabled else "morning_off"), None)


def turn_off(services: Services, hi: HandlerInput) -> Response:
    return _set(services, hi, False)


def turn_on(services: Services, hi: HandlerInput) -> Response:
    return _set(services, hi, True)
