"""Strukturierte JSON-Logs ohne Gesprächsinhalte, plus CloudWatch-Metriken im EMF-Format.

Regel: Niemals Nutzereingaben, Modellantworten, Hörbuchtitel oder rohe User-IDs loggen.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from typing import Any

NAMESPACE = "Superkugel"
_FORBIDDEN = {"text", "query", "answer", "prompt", "title", "user_id", "utterance", "speech"}


def log(event: str, **fields: Any) -> None:
    safe = {k: v for k, v in fields.items() if k not in _FORBIDDEN}
    print(json.dumps({"event": event, "ts": round(time.time(), 3), **safe}, default=str), file=sys.stdout)


def metric(name: str, value: float, unit: str = "Count", **dims: str) -> None:
    """Schreibt eine Metrik im Embedded Metric Format (keine zusätzlichen API-Aufrufe)."""
    doc: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {"Namespace": NAMESPACE, "Dimensions": [list(dims)] if dims else [[]],
                 "Metrics": [{"Name": name, "Unit": unit}]}
            ],
        },
        name: value,
        **dims,
    }
    print(json.dumps(doc), file=sys.stdout)


def hash_user(user_id: str, device_id: str = "") -> str:
    """Pseudonymisierte Kennung für Speicherung und Logs.

    Konto + Gerät: Alle Echos eines Amazon-Kontos haben dieselbe userId. Läuft der Skill über das
    Konto des Admins, bekäme sonst z. B. der Echo des Admins denselben Hörbuchstand und Gesprächsverlauf
    wie der Echo der Nutzerin. Pro Gerät getrennt = pro Person getrennt.
    """
    raw = f"{user_id}|{device_id}" if device_id else user_id
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
