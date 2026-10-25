"""OpenAI-Anbindung über die Responses API.

Bewusst ohne OpenAI-SDK: nur Standardbibliothek → kein pydantic/httpx im Lambda-Paket,
kürzerer Kaltstart, volle Kontrolle über Timeouts. Die REST-Schnittstelle ist dokumentiert
und stabil (POST /v1/responses).
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from superkugel.services.usage import TokenUsage

Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


class LlmError(Exception):
    def __init__(self, kind: str, status: int | None = None) -> None:
        super().__init__(kind)
        self.kind = kind  # timeout | network | rate_limit | quota | server | auth | bad_request | bad_response | no_key
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.kind in ("timeout", "network", "rate_limit", "server")


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class LlmReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    truncated: bool = False
    latency_ms: int = 0


def urllib_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310 - feste HTTPS-Basis-URL
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - feste HTTPS-URL
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except TimeoutError as exc:
        raise LlmError("timeout") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise LlmError("timeout") from exc
        raise LlmError("network") from exc
    except OSError as exc:
        raise LlmError("network") from exc


def parse_response(data: dict[str, Any]) -> LlmReply:
    texts: list[str] = []
    calls: list[ToolCall] = []
    for item in data.get("output", []) or []:
        if item.get("type") == "message":
            for part in item.get("content", []) or []:
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
        elif item.get("type") == "function_call":
            try:
                args = json.loads(item.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(name=str(item.get("name", "")), arguments=args if isinstance(args, dict) else {}))
    u = data.get("usage") or {}
    usage = TokenUsage(
        input_tokens=int(u.get("input_tokens", 0)),
        cached_input_tokens=int((u.get("input_tokens_details") or {}).get("cached_tokens", 0)),
        output_tokens=int(u.get("output_tokens", 0)),
    )
    truncated = data.get("status") == "incomplete"
    text = " ".join(t.strip() for t in texts if t.strip())
    if not text and not calls:
        raise LlmError("bad_response")
    return LlmReply(text=text, tool_calls=calls, usage=usage, truncated=truncated)


class OpenAIClient:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1",
                 reasoning_effort: str = "none", max_output_tokens: int = 350,
                 transport: Transport = urllib_transport, clock: Callable[[], float] = time.monotonic) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.transport = transport
        self.clock = clock

    def _payload(self, instructions: str, messages: list[dict[str, str]],
                 tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": messages,
            "max_output_tokens": self.max_output_tokens,
            "store": False,  # Gespräche nicht bei OpenAI speichern
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if tools:
            payload["tools"] = tools
        return payload

    def complete(self, instructions: str, messages: list[dict[str, str]], *, deadline: float,
                 tools: list[dict[str, Any]] | None = None, max_attempts: int = 2,
                 min_retry_budget_s: float = 2.5) -> LlmReply:
        """Ruft das Modell auf. ``deadline`` ist ein absoluter Zeitpunkt (clock()).

        Höchstens ein Wiederholungsversuch, und nur wenn bis zur Deadline genug Zeit bleibt.
        """
        body = json.dumps(self._payload(instructions, messages, tools)).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last: LlmError | None = None
        for attempt in range(max_attempts):
            remaining = deadline - self.clock()
            if remaining <= 0.3 or (attempt > 0 and remaining < min_retry_budget_s):
                break
            start = self.clock()
            try:
                status, raw = self.transport(f"{self.base_url}/responses", headers, body, remaining)
            except LlmError as exc:
                last = exc
                if not exc.retryable:
                    raise
                continue
            if status == 200:
                try:
                    reply = parse_response(json.loads(raw))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise LlmError("bad_response", status) from exc
                reply.latency_ms = int((self.clock() - start) * 1000)
                return reply
            last = _status_error(status, raw)
            if not last.retryable:
                raise last
        raise last or LlmError("timeout")


def _status_error(status: int, raw: bytes = b"") -> LlmError:
    if status in (401, 403):
        return LlmError("auth", status)
    if status == 429 and b"insufficient_quota" in raw:
        return LlmError("quota", status)  # Guthaben/Budget aufgebraucht: nicht wiederholen
    if status == 429:
        return LlmError("rate_limit", status)
    if status >= 500:
        return LlmError("server", status)
    return LlmError("bad_request", status)
