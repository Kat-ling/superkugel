"""Live-Radio über den AudioPlayer.

Eigenes Token-Präfix ``radio-``: Hörbuch-Logik (``player.parse_token``) erkennt diese Tokens nicht und schreibt
deshalb nie ein Lesezeichen – das Hörbuch-Lesezeichen bleibt unberührt. Kein Offset (live), Pause = Stopp,
„weiter“ startet den Sender neu, „nächster/vorheriger“ wechselt den Sender.
"""

from __future__ import annotations

import time

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.interfaces.audioplayer import (
    AudioItem,
    AudioItemMetadata,
    PlayBehavior,
    PlayDirective,
    Stream,
)

from superkugel.handlers.common import (
    Services,
    audio_context,
    end_with,
    has_session,
    keep_open,
    session_attrs,
    slot,
    uid,
)
from superkugel.radio import stations
from superkugel.radio.stations import Station
from superkugel.services.logs import log


def _directive(station: Station) -> PlayDirective:
    return PlayDirective(
        play_behavior=PlayBehavior.REPLACE_ALL,
        audio_item=AudioItem(
            stream=Stream(token=stations.token_for(station), url=station.url, offset_in_milliseconds=0),
            metadata=AudioItemMetadata(title=station.name, subtitle="Live"),
        ),
    )


def _remember(services: Services, hi: HandlerInput, station: Station) -> None:
    """Zuletzt gehörter Sender (für „Alexa, weiter“) – eigener Eintrag, nicht der Hörbuch-Zustand."""
    try:
        services.store.put_item(f"USER#{uid(hi)}", "RADIO", {"station": station.station_id, "at": time.time()},
                               ttl_s=30 * 86400)
    except Exception as exc:  # noqa: BLE001
        log("radio_state_failed", error=type(exc).__name__)


def play(services: Services, hi: HandlerInput, station: Station, intro: bool = True) -> Response:
    if stations.is_down(services.store, station, services.settings):
        return end_with(services, hi, services.t("radio_down", name=station.name))
    _remember(services, hi, station)
    services.count("radio")
    log("radio_start", station=station.station_id)
    if has_session(hi):
        session_attrs(hi).pop("pending", None)
    rb = hi.response_builder.add_directive(_directive(station)).set_should_end_session(True)
    if intro:
        rb.speak(services.say(services.t("radio_start", name=station.name)))
    return rb.response


def play_intent(services: Services, hi: HandlerInput) -> Response:
    raw = slot(hi, "station")
    station = stations.match(raw, services.settings) if raw else None
    listing = stations.listing(services.settings)
    if station:
        return play(services, hi, station)
    if raw:
        # Kein Sender: Antwort in einem laufenden Dialog (Rätsel „Wien“, Erinnerung „Tabletten“) oder ein
        # Hörbuch-/Sendungswunsch („spiel Der Hobbit“ landet wegen des offenen Slots oft hier)
        from superkugel.handlers.conversation import route_pending

        routed = route_pending(services, hi, raw, services.clock()) if has_session(hi) else None
        if routed is not None:
            return routed
        if any(w in raw.lower().split() for w in ("radio", "sender", "radiosender")):
            return keep_open(services, hi, services.t("radio_unknown", listing=listing),
                             services.t("radio_which", listing=listing))
        from superkugel.handlers import audio

        return audio.play_raw(services, hi, raw, services.clock())
    return keep_open(services, hi, services.t("radio_which", listing=listing), services.t("radio_which", listing=listing))


def list_intent(services: Services, hi: HandlerInput) -> Response:
    return keep_open(services, hi, services.t("radio_list", listing=stations.listing(services.settings)), None)


def current(services: Services, hi: HandlerInput, active_only: bool = False) -> Station | None:
    """Sender, wenn der AudioPlayer zuletzt Radio spielte. ``active_only``: nur, wenn es gerade läuft (oder
    pausiert) – Alexa behält den letzten Token auch nach dem Stopp; sonst übernähme gestriges Radio heute
    „nächstes Kapitel“ oder „was läuft“."""
    token, _ = audio_context(hi)
    if active_only:
        ap = getattr(hi.request_envelope.context, "audio_player", None)
        activity = str(getattr(ap, "player_activity", "") or "")
        if not activity.endswith(("PLAYING", "PAUSED")):
            return None
    return stations.station_from_token(token, services.settings)


def last_played(services: Services, hi: HandlerInput) -> tuple[Station, float] | None:
    try:
        d = services.store.get_item(f"USER#{uid(hi)}", "RADIO")
    except Exception:  # noqa: BLE001
        return None
    st = stations.by_id(str((d or {}).get("station", "")), services.settings)
    return (st, float(d.get("at", 0))) if st and d else None


def neighbour(services: Services, station: Station, step: int) -> Station:
    lst = stations.stations(services.settings)
    idx = next((i for i, s in enumerate(lst) if s.station_id == station.station_id), 0)
    return lst[(idx + step) % len(lst)]


def switch(services: Services, hi: HandlerInput, station: Station, step: int) -> Response:
    return play(services, hi, neighbour(services, station, step))


def no_seek(services: Services, hi: HandlerInput) -> Response:
    return end_with(services, hi, services.t("radio_no_seek"))


def whats_playing(services: Services, hi: HandlerInput, station: Station) -> Response:
    return end_with(services, hi, services.t("radio_whats", name=station.name))


def directive_for(station: Station) -> PlayDirective:
    """Für PlaybackController-Ereignisse (dort keine Sprache erlaubt)."""
    return _directive(station)
