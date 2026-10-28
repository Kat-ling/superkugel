"""Reine Tageszähler (Wiener Zeit) für den Wochenbericht – nur Zahlen, nie Inhalte."""

from __future__ import annotations

import datetime as dt

from superkugel.config import Settings
from superkugel.services.logs import log
from superkugel.services.storage import Store
from superkugel.services.usage import local_now

STATS_TTL_S = 45 * 86400  # Wochen- und Monatsvergleich möglich, danach löscht DynamoDB automatisch
# alexa_hint = Hinweis „Das macht Alexa selbst“ (Erinnerung, Radio, Rätsel)
FIELDS = ("sessions", "chat", "audiobook", "show", "morning", "media_search", "alexa_hint", "errors", "slow")


def count(store: Store, settings: Settings, field: str, n: int = 1, now: dt.datetime | None = None) -> None:
    """Zähler erhöhen. Fehler werden nur protokolliert – ein Zähler darf nie eine Antwort verhindern."""
    if field not in FIELDS:
        raise ValueError(field)
    day = local_now(settings, now).strftime("%Y-%m-%d")
    try:
        store.add_stats(day, {field: n}, STATS_TTL_S)
    except Exception as exc:  # noqa: BLE001
        log("stats_write_failed", error=type(exc).__name__)
