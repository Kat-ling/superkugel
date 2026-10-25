"""Token-/Suchzählung, Kostenschätzung und harte Nutzungsschranken.

Alle Tages- und Monatsgrenzen laufen in **Wiener Zeit** (nicht UTC), damit „heute“ um Mitternacht endet.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from superkugel.config import Settings
from superkugel.services.logs import log, metric
from superkugel.services.storage import Store


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    search_calls: int = 0


def estimate_cost_usd(usage: TokenUsage, settings: Settings) -> float:
    uncached = max(0, usage.input_tokens - usage.cached_input_tokens)
    tokens = (
        uncached * settings.price_input_per_m
        + usage.cached_input_tokens * settings.price_cached_input_per_m
        + usage.output_tokens * settings.price_output_per_m
    ) / 1_000_000
    return tokens + usage.search_calls * settings.web_search_price_usd


def local_now(settings: Settings, now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    return now.astimezone(ZoneInfo(settings.timezone))


def _keys(local: dt.datetime) -> tuple[str, str]:
    return local.strftime("%Y-%m-%d"), local.strftime("%Y-%m")


class UsageGuard:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def limit_reached(self, now: dt.datetime | None = None) -> bool:
        day, month = _keys(local_now(self.settings, now))
        try:
            d = self.store.get_usage(f"DAY#{day}").cost_usd
            m = self.store.get_usage(f"MONTH#{month}").cost_usd
        except Exception as exc:  # noqa: BLE001 - Ratschen ist billig; Prepaid bei OpenAI bleibt letzte Grenze
            log("usage_read_error", error=type(exc).__name__)
            return False
        return d >= self.settings.daily_cost_limit_usd or m >= self.settings.monthly_cost_limit_usd

    def searches_left(self, now: dt.datetime | None = None) -> int:
        """Restkontingent Websuche heute. Bei Lesefehler 0 (Websuche ist der teure Teil → im Zweifel aus)."""
        if not self.settings.web_search_enabled or self.settings.web_search_daily_limit <= 0:
            return 0
        day, month = _keys(local_now(self.settings, now))
        try:
            d = self.store.get_usage(f"DAY#{day}")
            m = self.store.get_usage(f"MONTH#{month}")
        except Exception as exc:  # noqa: BLE001
            log("usage_read_error", error=type(exc).__name__)
            return 0
        # Eine Suche darf das Tages-/Monatslimit nicht mehr überschreiten.
        reserve = self.settings.web_search_price_usd + 0.002
        if d.cost_usd + reserve > self.settings.daily_cost_limit_usd:
            return 0
        if m.cost_usd + reserve > self.settings.monthly_cost_limit_usd:
            return 0
        return max(0, self.settings.web_search_daily_limit - d.searches)

    def media_searches_left(self, now: dt.datetime | None = None) -> int:
        day, _ = _keys(local_now(self.settings, now))
        try:
            used = self.store.get_counter(f"MEDIA#{day}")
        except Exception as exc:  # noqa: BLE001
            log("usage_read_error", error=type(exc).__name__)
            return 0
        return max(0, self.settings.media_search_daily_limit - used)

    def record_media_search(self, now: dt.datetime | None = None) -> None:
        day, _ = _keys(local_now(self.settings, now))
        try:
            self.store.incr_counter(f"MEDIA#{day}", ttl_s=3 * 86400)
        except Exception as exc:  # noqa: BLE001
            log("usage_write_error", error=type(exc).__name__)

    def record(self, usage: TokenUsage, latency_ms: int, now: dt.datetime | None = None) -> float:
        cost = estimate_cost_usd(usage, self.settings)
        day, month = _keys(local_now(self.settings, now))
        try:
            self.store.add_usage(day, month, usage.input_tokens, usage.output_tokens, round(cost * 1_000_000),
                                 searches=usage.search_calls)
        except Exception as exc:  # noqa: BLE001
            log("usage_write_error", error=type(exc).__name__)
        log("llm_usage", input_tokens=usage.input_tokens, cached=usage.cached_input_tokens,
            output_tokens=usage.output_tokens, searches=usage.search_calls, cost_usd=round(cost, 6),
            latency_ms=latency_ms)
        metric("LlmCostMicroUsd", round(cost * 1_000_000))
        return cost
