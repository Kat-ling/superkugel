"""Persistenz: eine DynamoDB-Tabelle (pk/sk) bzw. In-Memory-Variante für Tests.

Layout:
  pk=LIBRARY        sk=BOOK#<id>         Hörbuch-Metadaten (JSON)
  pk=USER#<hash>    sk=STATE             aktuelles Hörbuch, letzter Token
  pk=USER#<hash>    sk=PROGRESS#<id>     Wiedergabefortschritt je Buch
  pk=USER#<hash>    sk=CONVERSATION      kurzer Gesprächsverlauf (TTL)
  pk=USAGE          sk=DAY#<yyyy-mm-dd>  Token-/Kostenzähler
  pk=USAGE          sk=MONTH#<yyyy-mm>
  pk=OPS            sk=CIRCUIT           Fehlerzähler für die KI-Anbindung
  pk=OPS            sk=COUNTER#<name>    einfache Zähler (z. B. Mediensuchen pro Tag, mit TTL)
  pk=CONTEXT        sk=CURRENT           Schlagzeilen + Wetter (stündlich aktualisiert)
  pk=PODCASTS       sk=SHOW#<id>         Lieblingssendungen mit den neuesten Folgen
  pk=EPISODES       sk=EP#<id>           abgespielte Folgen (für Lesezeichen/AudioPlayer-Ereignisse)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from superkugel.audiobooks.models import Book, Progress


@dataclass
class UsageTotals:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micro_usd: int = 0
    searches: int = 0

    @property
    def cost_usd(self) -> float:
        return self.cost_micro_usd / 1_000_000


def fast_aws_config() -> Any:
    """Kurze Timeouts: ein hängender AWS-Dienst darf das 8-s-Budget von Alexa nicht aufbrauchen."""
    from botocore.config import Config

    return Config(connect_timeout=1, read_timeout=2, retries={"max_attempts": 2, "mode": "standard"})


class Store(Protocol):
    def list_books(self) -> list[Book]: ...
    def get_book(self, book_id: str) -> Book | None: ...
    def put_book(self, book: Book) -> None: ...
    def delete_book(self, book_id: str) -> None: ...

    def get_state(self, uid: str) -> dict[str, Any]: ...
    def put_state(self, uid: str, state: dict[str, Any]) -> None: ...
    def get_progress(self, uid: str, book_id: str) -> Progress | None: ...
    def put_progress(self, uid: str, progress: Progress) -> None: ...
    def list_progress(self, uid: str) -> list[Progress]: ...

    def get_conversation(self, uid: str) -> dict[str, Any] | None: ...
    def put_conversation(self, uid: str, data: dict[str, Any], ttl_s: int) -> None: ...
    def delete_conversation(self, uid: str) -> None: ...

    def add_usage(self, day: str, month: str, inp: int, out: int, cost_micro: int, searches: int = 0) -> None: ...
    def get_usage(self, period_key: str) -> UsageTotals: ...
    def incr_counter(self, name: str, ttl_s: int = 0) -> int: ...
    def get_counter(self, name: str) -> int: ...

    def get_item(self, pk: str, sk: str) -> dict[str, Any] | None: ...
    def put_item(self, pk: str, sk: str, data: dict[str, Any], ttl_s: int = 0) -> None: ...
    def query_items(self, pk: str, prefix: str) -> list[dict[str, Any]]: ...
    def delete_item(self, pk: str, sk: str) -> None: ...

    def get_circuit(self) -> dict[str, Any]: ...
    def put_circuit(self, data: dict[str, Any]) -> None: ...


class MemoryStore:
    """Einfache In-Memory-Implementierung (lokale Tests, Entwicklung)."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.usage: dict[str, UsageTotals] = {}

    # Bibliothek
    def list_books(self) -> list[Book]:
        return [Book.from_dict(v) for (pk, _), v in sorted(self.items.items()) if pk == "LIBRARY"]

    def get_book(self, book_id: str) -> Book | None:
        v = self.items.get(("LIBRARY", f"BOOK#{book_id}"))
        return Book.from_dict(v) if v else None

    def put_book(self, book: Book) -> None:
        self.items[("LIBRARY", f"BOOK#{book.book_id}")] = book.to_dict()

    def delete_book(self, book_id: str) -> None:
        self.items.pop(("LIBRARY", f"BOOK#{book_id}"), None)

    # Nutzerzustand
    def get_state(self, uid: str) -> dict[str, Any]:
        return dict(self.items.get((f"USER#{uid}", "STATE"), {}))

    def put_state(self, uid: str, state: dict[str, Any]) -> None:
        self.items[(f"USER#{uid}", "STATE")] = dict(state)

    def get_progress(self, uid: str, book_id: str) -> Progress | None:
        v = self.items.get((f"USER#{uid}", f"PROGRESS#{book_id}"))
        return Progress.from_dict(v) if v else None

    def put_progress(self, uid: str, progress: Progress) -> None:
        self.items[(f"USER#{uid}", f"PROGRESS#{progress.book_id}")] = progress.to_dict()

    def list_progress(self, uid: str) -> list[Progress]:
        return [
            Progress.from_dict(v)
            for (pk, sk), v in self.items.items()
            if pk == f"USER#{uid}" and sk.startswith("PROGRESS#")
        ]

    # Gespräch
    def get_conversation(self, uid: str) -> dict[str, Any] | None:
        v = self.items.get((f"USER#{uid}", "CONVERSATION"))
        if not v or v.get("expires_at", 0) < time.time():
            return None
        return dict(v)

    def put_conversation(self, uid: str, data: dict[str, Any], ttl_s: int) -> None:
        self.items[(f"USER#{uid}", "CONVERSATION")] = {**data, "expires_at": int(time.time()) + ttl_s}

    def delete_conversation(self, uid: str) -> None:
        self.items.pop((f"USER#{uid}", "CONVERSATION"), None)

    # Nutzung
    def add_usage(self, day: str, month: str, inp: int, out: int, cost_micro: int, searches: int = 0) -> None:
        for key in (f"DAY#{day}", f"MONTH#{month}"):
            t = self.usage.setdefault(key, UsageTotals())
            t.requests += 1
            t.input_tokens += inp
            t.output_tokens += out
            t.cost_micro_usd += cost_micro
            t.searches += searches

    def get_usage(self, period_key: str) -> UsageTotals:
        return self.usage.get(period_key, UsageTotals())

    def incr_counter(self, name: str, ttl_s: int = 0) -> int:
        item = self.items.setdefault(("OPS", f"COUNTER#{name}"), {"value": 0})
        item["value"] += 1
        return int(item["value"])

    def get_counter(self, name: str) -> int:
        return int(self.items.get(("OPS", f"COUNTER#{name}"), {}).get("value", 0))

    def get_item(self, pk: str, sk: str) -> dict[str, Any] | None:
        v = self.items.get((pk, sk))
        if not v or (v.get("expires_at") and v["expires_at"] < time.time()):
            return None
        return dict(v)

    def put_item(self, pk: str, sk: str, data: dict[str, Any], ttl_s: int = 0) -> None:
        self.items[(pk, sk)] = {**data, **({"expires_at": int(time.time()) + ttl_s} if ttl_s else {})}

    def query_items(self, pk: str, prefix: str) -> list[dict[str, Any]]:
        return [dict(v) for (p, k), v in sorted(self.items.items()) if p == pk and k.startswith(prefix)]

    def delete_item(self, pk: str, sk: str) -> None:
        self.items.pop((pk, sk), None)

    # Betrieb
    def get_circuit(self) -> dict[str, Any]:
        return dict(self.items.get(("OPS", "CIRCUIT"), {}))

    def put_circuit(self, data: dict[str, Any]) -> None:
        self.items[("OPS", "CIRCUIT")] = dict(data)


class DynamoStore:
    """DynamoDB-Implementierung. Nutzdaten liegen als JSON im Attribut ``data``."""

    def __init__(self, table_name: str, region: str, resource: Any | None = None) -> None:
        if resource is None:
            import boto3

            resource = boto3.resource("dynamodb", region_name=region, config=fast_aws_config())
        self.table = resource.Table(table_name)

    def _get(self, pk: str, sk: str) -> dict[str, Any] | None:
        item = self.table.get_item(Key={"pk": pk, "sk": sk}).get("Item")
        if not item:
            return None
        return json.loads(item["data"]) if "data" in item else None

    def _put(self, pk: str, sk: str, data: dict[str, Any], expires_at: int | None = None) -> None:
        item: dict[str, Any] = {"pk": pk, "sk": sk, "data": json.dumps(data, ensure_ascii=False)}
        if expires_at is not None:
            item["expires_at"] = expires_at
        self.table.put_item(Item=item)

    def _query(self, pk: str, prefix: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        out: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix)
        }
        while True:
            resp = self.table.query(**kwargs)
            out.extend(json.loads(i["data"]) for i in resp.get("Items", []) if "data" in i)
            if "LastEvaluatedKey" not in resp:
                return out
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def list_books(self) -> list[Book]:
        return [Book.from_dict(d) for d in self._query("LIBRARY", "BOOK#")]

    def get_book(self, book_id: str) -> Book | None:
        d = self._get("LIBRARY", f"BOOK#{book_id}")
        return Book.from_dict(d) if d else None

    def put_book(self, book: Book) -> None:
        self._put("LIBRARY", f"BOOK#{book.book_id}", book.to_dict())

    def delete_book(self, book_id: str) -> None:
        self.table.delete_item(Key={"pk": "LIBRARY", "sk": f"BOOK#{book_id}"})

    def get_state(self, uid: str) -> dict[str, Any]:
        return self._get(f"USER#{uid}", "STATE") or {}

    def put_state(self, uid: str, state: dict[str, Any]) -> None:
        self._put(f"USER#{uid}", "STATE", state)

    def get_progress(self, uid: str, book_id: str) -> Progress | None:
        d = self._get(f"USER#{uid}", f"PROGRESS#{book_id}")
        return Progress.from_dict(d) if d else None

    def put_progress(self, uid: str, progress: Progress) -> None:
        self._put(f"USER#{uid}", f"PROGRESS#{progress.book_id}", progress.to_dict())

    def list_progress(self, uid: str) -> list[Progress]:
        return [Progress.from_dict(d) for d in self._query(f"USER#{uid}", "PROGRESS#")]

    def get_conversation(self, uid: str) -> dict[str, Any] | None:
        d = self._get(f"USER#{uid}", "CONVERSATION")
        # DynamoDB-TTL löscht verzögert, daher zusätzlich selbst prüfen.
        if not d or d.get("expires_at", 0) < time.time():
            return None
        return d

    def put_conversation(self, uid: str, data: dict[str, Any], ttl_s: int) -> None:
        expires = int(time.time()) + ttl_s
        self._put(f"USER#{uid}", "CONVERSATION", {**data, "expires_at": expires}, expires_at=expires)

    def delete_conversation(self, uid: str) -> None:
        self.table.delete_item(Key={"pk": f"USER#{uid}", "sk": "CONVERSATION"})

    def add_usage(self, day: str, month: str, inp: int, out: int, cost_micro: int, searches: int = 0) -> None:
        for sk in (f"DAY#{day}", f"MONTH#{month}"):
            self.table.update_item(
                Key={"pk": "USAGE", "sk": sk},
                UpdateExpression="ADD requests :one, input_tokens :i, output_tokens :o, cost_micro_usd :c, searches :s",
                ExpressionAttributeValues={":one": 1, ":i": inp, ":o": out, ":c": cost_micro, ":s": searches},
            )

    def incr_counter(self, name: str, ttl_s: int = 0) -> int:
        kwargs: dict[str, Any] = {
            "Key": {"pk": "OPS", "sk": f"COUNTER#{name}"},
            "UpdateExpression": "ADD #v :one" + (" SET expires_at = if_not_exists(expires_at, :exp)" if ttl_s else ""),
            "ExpressionAttributeNames": {"#v": "value"},
            "ExpressionAttributeValues": {":one": 1, **({":exp": int(time.time()) + ttl_s} if ttl_s else {})},
            "ReturnValues": "UPDATED_NEW",
        }
        resp = self.table.update_item(**kwargs)
        return int(resp.get("Attributes", {}).get("value", 0))

    def get_counter(self, name: str) -> int:
        item = self.table.get_item(Key={"pk": "OPS", "sk": f"COUNTER#{name}"}).get("Item") or {}
        return int(item.get("value", 0))

    def get_item(self, pk: str, sk: str) -> dict[str, Any] | None:
        d = self._get(pk, sk)
        if d and d.get("expires_at") and d["expires_at"] < time.time():
            return None
        return d

    def put_item(self, pk: str, sk: str, data: dict[str, Any], ttl_s: int = 0) -> None:
        expires = int(time.time()) + ttl_s if ttl_s else None
        self._put(pk, sk, {**data, **({"expires_at": expires} if expires else {})}, expires_at=expires)

    def query_items(self, pk: str, prefix: str) -> list[dict[str, Any]]:
        return self._query(pk, prefix)

    def delete_item(self, pk: str, sk: str) -> None:
        self.table.delete_item(Key={"pk": pk, "sk": sk})

    def get_usage(self, period_key: str) -> UsageTotals:
        item = self.table.get_item(Key={"pk": "USAGE", "sk": period_key}).get("Item") or {}
        return UsageTotals(
            requests=int(item.get("requests", 0)),
            input_tokens=int(item.get("input_tokens", 0)),
            output_tokens=int(item.get("output_tokens", 0)),
            cost_micro_usd=int(item.get("cost_micro_usd", 0)),
            searches=int(item.get("searches", 0)),
        )

    def get_circuit(self) -> dict[str, Any]:
        return self._get("OPS", "CIRCUIT") or {}

    def put_circuit(self, data: dict[str, Any]) -> None:
        self._put("OPS", "CIRCUIT", data)
