"""Token-Zählung, Kostenschätzung und harte Nutzungsschranken."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from superkugel.config import Settings
from superkugel.services.logs import log, metric
from superkugel.services.storage import Store


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0


def estimate_cost_usd(usage: TokenUsage, settings: Settings) -> float:
    uncached = max(0, usage.input_tokens - usage.cached_input_tokens)
    return (
        uncached * settings.price_input_per_m
        + usage.cached_input_tokens * settings.price_cached_input_per_m
        + usage.output_tokens * settings.price_output_per_m
    ) / 1_000_000


def _keys(now: dt.datetime) -> tuple[str, str]:
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")


class UsageGuard:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def limit_reached(self, now: dt.datetime | None = None) -> bool:
        day, month = _keys(now or dt.datetime.now(dt.UTC))
        try:
            d = self.store.get_usage(f"DAY#{day}").cost_usd
            m = self.store.get_usage(f"MONTH#{month}").cost_usd
        except Exception as exc:  # noqa: BLE001 - im Zweifel nicht blockieren, Budget bei OpenAI greift
            log("usage_read_error", error=type(exc).__name__)
            return False
        return d >= self.settings.daily_cost_limit_usd or m >= self.settings.monthly_cost_limit_usd

    def record(self, usage: TokenUsage, latency_ms: int, now: dt.datetime | None = None) -> float:
        cost = estimate_cost_usd(usage, self.settings)
        day, month = _keys(now or dt.datetime.now(dt.UTC))
        try:
            self.store.add_usage(day, month, usage.input_tokens, usage.output_tokens, round(cost * 1_000_000))
        except Exception as exc:  # noqa: BLE001
            log("usage_write_error", error=type(exc).__name__)
        log("llm_usage", input_tokens=usage.input_tokens, cached=usage.cached_input_tokens,
            output_tokens=usage.output_tokens, cost_usd=round(cost, 6), latency_ms=latency_ms)
        metric("LlmCostMicroUsd", round(cost * 1_000_000))
        metric("LlmLatency", latency_ms, unit="Milliseconds")
        return cost
