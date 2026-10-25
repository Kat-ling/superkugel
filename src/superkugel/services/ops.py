"""Betriebsmodus (Fernschalter), Secrets und Circuit-Breaker für die KI-Anbindung."""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from superkugel.config import Settings
from superkugel.services.logs import log
from superkugel.services.storage import Store


class Mode(StrEnum):
    NORMAL = "normal"  # alles an
    AUDIOBOOKS_ONLY = "audiobooks_only"  # KI aus, Hörbücher an
    MAINTENANCE = "maintenance"  # Skill verabschiedet sich sofort


class ParameterSource:
    """Liest SSM-Parameter mit kurzem Cache. Fällt bei Fehlern auf Standardwerte zurück."""

    def __init__(self, settings: Settings, ssm_client: Any | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.settings = settings
        self._ssm = ssm_client
        self._clock = clock
        self._mode: tuple[float, Mode] | None = None
        self._api_key: str | None = settings.openai_api_key or None

    def _client(self) -> Any:
        if self._ssm is None:
            import boto3

            from superkugel.services.storage import fast_aws_config

            self._ssm = boto3.client("ssm", region_name=self.settings.aws_region, config=fast_aws_config())
        return self._ssm

    def mode(self) -> Mode:
        now = self._clock()
        if self._mode and now - self._mode[0] < self.settings.mode_cache_s:
            return self._mode[1]
        value = self._mode[1] if self._mode else Mode.NORMAL  # letzter bekannter Wert
        try:
            raw = self._client().get_parameter(Name=self.settings.mode_param)["Parameter"]["Value"]
            value = Mode(raw.strip().lower())
        except ValueError:
            log("mode_invalid")
        except Exception as exc:  # noqa: BLE001 - Modus darf den Skill nie blockieren
            log("mode_unavailable", error=type(exc).__name__)
        self._mode = (now, value)
        return value

    def invalidate_api_key(self) -> None:
        """Nach einem Anmeldefehler: beim nächsten Mal neu aus SSM lesen (Schlüsselwechsel ohne Neudeploy)."""
        if not self.settings.openai_api_key:
            self._api_key = None

    def openai_api_key(self) -> str | None:
        if self._api_key:
            return self._api_key
        try:
            resp = self._client().get_parameter(
                Name=self.settings.openai_api_key_param, WithDecryption=True
            )
            self._api_key = resp["Parameter"]["Value"].strip() or None
        except Exception as exc:  # noqa: BLE001
            log("api_key_unavailable", error=type(exc).__name__)
            return None
        return self._api_key


class CircuitBreaker:
    """Öffnet nach mehreren KI-Fehlern in Folge und spart dann die 8-Sekunden-Wartezeit."""

    def __init__(self, store: Store, settings: Settings, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.settings = settings
        self.clock = clock

    def is_open(self) -> bool:
        try:
            data = self.store.get_circuit()
        except Exception:  # noqa: BLE001
            return False
        return float(data.get("open_until", 0)) > self.clock()

    def record_failure(self) -> None:
        try:
            data = self.store.get_circuit()
            failures = int(data.get("failures", 0)) + 1
            open_until = float(data.get("open_until", 0))
            if failures >= self.settings.circuit_failure_threshold:
                open_until = self.clock() + self.settings.circuit_open_s
                failures = 0
                log("circuit_opened", seconds=self.settings.circuit_open_s)
            self.store.put_circuit({"failures": failures, "open_until": open_until})
        except Exception as exc:  # noqa: BLE001
            log("circuit_store_error", error=type(exc).__name__)

    def record_success(self) -> None:
        try:
            data = self.store.get_circuit()
            if data.get("failures") or data.get("open_until"):
                self.store.put_circuit({"failures": 0, "open_until": 0})
        except Exception as exc:  # noqa: BLE001
            log("circuit_store_error", error=type(exc).__name__)
