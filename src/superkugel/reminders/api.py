"""Alexa Reminders API (/v1/alerts/reminders) – nur Standardbibliothek, kurzes Zeitlimit.

Doku (geprüft 27.10.2026): Anlegen nur während einer Sitzung mit dem ``apiAccessToken`` des Requests;
Berechtigung ``alexa::alerts:reminders:skill:readwrite``; ein Skill sieht/löscht nur eigene Erinnerungen.
Bewusst nicht über den SDK-``DefaultApiClient``: der hat kein Zeitlimit, das 8-s-Budget von Alexa aber schon.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

PERMISSION = "alexa::alerts:reminders:skill:readwrite"
TIMEOUT_S = 3.0
# Nur die offiziellen Alexa-API-Hosts bekommen das Token (apiEndpoint stammt aus dem Request).
_HOST = re.compile(r"^api(\.(eu|fe))?\.amazonalexa\.com$")

Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]


class ReminderError(Exception):
    """kind: permission | limit | past | unsupported | failed"""

    def __init__(self, kind: str, status: int | None = None) -> None:
        super().__init__(kind)
        self.kind, self.status = kind, status


@dataclass(frozen=True)
class Reminder:
    token: str
    when: dt.datetime | None  # Ortszeit laut Amazon (ohne Zeitzone gespeichert → mit tz ergänzt)
    text: str


MAX_RESPONSE = 256 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Weiterleitungen nie folgen: urllib würde den Authorization-Header mitschicken (Token-Abfluss)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None,
                     timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310 - Host geprüft
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(MAX_RESPONSE)
    except urllib.error.HTTPError as exc:  # auch 3xx (nicht gefolgt) → als Fehler behandelt
        return exc.code, exc.read(MAX_RESPONSE)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ReminderError("failed") from exc


class ReminderApi:
    def __init__(self, endpoint: str, token: str, tz: str, transport: Transport = urllib_transport,
                 timeout: float = TIMEOUT_S) -> None:
        parts = urllib.parse.urlsplit(endpoint or "")
        if parts.scheme != "https" or not _HOST.match(parts.hostname or "") or not token:
            raise ReminderError("failed")
        self.base = f"https://{parts.hostname}/v1/alerts/reminders"
        self.token, self.tz, self.transport, self.timeout = token, tz, transport, min(timeout, TIMEOUT_S)

    def _call(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        body = json.dumps(payload).encode() if payload is not None else None
        status, raw = self.transport(method, url, headers, body, self.timeout)
        if 200 <= status < 300:
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return {}
        code = ""
        with contextlib.suppress(json.JSONDecodeError, AttributeError):
            code = str((json.loads(raw) or {}).get("code", ""))
        if status == 401 or code in ("UNAUTHORIZED", "INVALID_BEARER_TOKEN"):
            raise ReminderError("permission", status)
        if code == "MAX_REMINDERS_EXCEEDED":
            raise ReminderError("limit", status)
        if code == "DEVICE_NOT_SUPPORTED":
            raise ReminderError("unsupported", status)
        if code == "TRIGGER_SCHEDULED_TIME_IN_PAST":
            raise ReminderError("past", status)
        if status == 403:
            raise ReminderError("permission", status)
        raise ReminderError("failed", status)

    def create(self, when: dt.datetime, text: str, now: dt.datetime) -> str:
        """Feste Uhrzeit (SCHEDULED_ABSOLUTE) in Ortszeit + Zeitzone – Sommer-/Winterzeit rechnet Amazon."""
        local = when.astimezone(when.tzinfo)
        payload = {
            "requestTime": now.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.000"),
            "trigger": {"type": "SCHEDULED_ABSOLUTE", "scheduledTime": local.strftime("%Y-%m-%dT%H:%M:%S.000"),
                        "timeZoneId": self.tz},
            "alertInfo": {"spokenInfo": {"content": [{"locale": "de-DE", "text": text}]}},
            "pushNotification": {"status": "ENABLED"},
        }
        data = self._call("POST", self.base, payload)
        return str(data.get("alertToken", ""))

    def list(self) -> list[Reminder]:
        """Nur aktive Erinnerungen dieses Skills, nach Zeit sortiert."""
        from zoneinfo import ZoneInfo

        data = self._call("GET", self.base)
        out: list[Reminder] = []
        for a in data.get("alerts") or []:
            if str(a.get("status", "ON")) != "ON":
                continue
            trig = a.get("trigger") or {}
            when: dt.datetime | None = None
            raw = str(trig.get("scheduledTime") or "")
            try:
                when = dt.datetime.fromisoformat(raw.rstrip("Z")[:19])
                when = when.replace(tzinfo=ZoneInfo(str(trig.get("timeZoneId") or self.tz)))
            except Exception:  # noqa: BLE001 - z. B. unbekannte timeZoneId: ohne Zeit vorlesen statt abzustürzen
                when = None
            content = ((a.get("alertInfo") or {}).get("spokenInfo") or {}).get("content") or [{}]
            out.append(Reminder(token=str(a.get("alertToken", "")), when=when, text=str(content[0].get("text", ""))))
        far = dt.datetime.max.replace(tzinfo=dt.UTC)
        return sorted((r for r in out if r.token), key=lambda r: r.when or far)

    def delete(self, alert_token: str) -> None:
        self._call("DELETE", f"{self.base}/{urllib.parse.quote(alert_token, safe='')}")
