"""Wochenbericht an den Admin: nur Zahlen – keine Fragen, Titel, Namen oder Orte.

Versand über das bestehende SNS-Alarmthema (E-Mail an den Admin). Ausgelöst montags früh vom Zeitplan;
der Code sendet nur um 8 Uhr Wiener Zeit und höchstens einmal pro Woche (EventBridge-Regeln rechnen in UTC,
deshalb zwei Auslösungen und die Prüfung hier – das deckt Sommer- und Winterzeit ab).
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from superkugel.config import Settings
from superkugel.services.logs import log
from superkugel.services.stats import FIELDS
from superkugel.services.storage import Store
from superkugel.services.usage import local_now

SEND_HOUR = 8
REPORT_TTL_S = 14 * 86400

# Einzige Felder, die der Bericht enthalten darf (Test prüft das aktiv).
ALLOWED_KEYS = {
    "week_from", "week_to", "days", *FIELDS, "chat_requests", "web_searches", "cost_week_usd", "cost_month_usd",
    "daily_limit_usd", "monthly_limit_usd", "month", "context_age_h", "new_audiobooks",
}


def build(store: Store, settings: Settings, now: dt.datetime | None = None,
          clock: float | None = None) -> dict[str, Any]:
    """Die letzten 7 vollen Tage (Wiener Zeit) bis gestern."""
    local = local_now(settings, now)
    end = local.date() - dt.timedelta(days=1)
    days = [end - dt.timedelta(days=i) for i in range(6, -1, -1)]
    totals = dict.fromkeys(FIELDS, 0)
    chat, searches, cost_micro = 0, 0, 0
    for d in days:
        key = d.isoformat()
        for k, v in store.get_stats(key).items():
            if k in totals:
                totals[k] += int(v)
        u = store.get_usage(f"DAY#{key}")
        chat, searches, cost_micro = chat + u.requests, searches + u.searches, cost_micro + u.cost_micro_usd
    month_key = f"{days[0]:%Y-%m}"  # Monat, in dem die Berichtswoche beginnt (am 1. wäre „heute“ fast leer)
    month = store.get_usage(f"MONTH#{month_key}")
    now_ts = clock if clock is not None else time.time()
    ctx = store.get_item("CONTEXT", "CURRENT") or {}
    stamps = [float(v["at"]) for k, v in ctx.items() if isinstance(v, dict) and "at" in v]
    cutoff = dt.datetime.combine(days[0], dt.time(), tzinfo=local.tzinfo).astimezone(dt.UTC).isoformat()
    new_books = sum(1 for b in store.list_books() if (b.imported_at or "") >= cutoff)
    report = {
        "week_from": days[0].isoformat(), "week_to": end.isoformat(), "days": len(days), **totals,
        "chat_requests": chat, "web_searches": searches,
        "cost_week_usd": round(cost_micro / 1_000_000, 4), "cost_month_usd": round(month.cost_usd, 4), "month": month_key,
        "daily_limit_usd": settings.daily_cost_limit_usd, "monthly_limit_usd": settings.monthly_cost_limit_usd,
        "context_age_h": round((now_ts - max(stamps)) / 3600, 1) if stamps else None,
        "new_audiobooks": new_books,
    }
    if not set(report) <= ALLOWED_KEYS:  # Schutz vor versehentlich neuen (inhaltlichen) Feldern
        raise ValueError("unerlaubtes Berichtsfeld")
    return report


def render(r: dict[str, Any]) -> str:
    """Klartext für die Mail. Nur Zahlen."""
    lines = [
        f"Superkugel – Wochenbericht {r['week_from']} bis {r['week_to']} (Wiener Zeit)",
        "",
        "Nutzung",
        f"  Sitzungen (Superkugel geöffnet): {r['sessions']}",
        f"  Gesprächsfragen an die KI:       {r['chat_requests']}",
        f"  Websuchen:                       {r['web_searches']}",
        f"  Mediensuchen:                    {r['media_search']}",
        f"  Hörbuch-Starts:                  {r['audiobook']}",
        f"  Sendungs-Starts:                 {r['show']}",
        f"  Morgengrüße:                     {r['morning']}",
        f"  Hinweise „macht Alexa selbst“:   {r['alexa_hint']}",
        "",
        "Kosten (geschätzt, KI inkl. Websuche)",
        f"  Woche: {r['cost_week_usd']:.4f} $   Monat {r['month']}: {r['cost_month_usd']:.4f} $",
        f"  Grenzen: {r['daily_limit_usd']:.2f} $/Tag, {r['monthly_limit_usd']:.2f} $/Monat",
        "",
        "Betrieb",
        f"  Fehler (abgefangen):             {r['errors']}",
        f"  Langsame Antworten (> 6,5 s):    {r['slow']}",
        "  Alter der Nachrichten/Wetterdaten: "
        + (f"{r['context_age_h']} h" if r["context_age_h"] is not None else "keine Daten"),
        f"  Neue Hörbücher:                  {r['new_audiobooks']}",
        "",
        "Inhalte (Fragen, Titel) sind bewusst nicht enthalten.",
    ]
    return "\n".join(lines)


def due(store: Store, settings: Settings, now: dt.datetime | None = None) -> str | None:
    """Wochenkennung, wenn jetzt gesendet werden soll (8-Uhr-Stunde, noch nicht gesendet); sonst None."""
    local = local_now(settings, now)
    if local.hour != SEND_HOUR:
        return None
    week = f"{local:%G-W%V}"
    return None if store.get_item("OPS", f"REPORT#{week}") else week


def send(store: Store, settings: Settings, publish: Any, now: dt.datetime | None = None,
         force: bool = False) -> dict[str, Any]:
    """Bericht bauen und per SNS senden. ``publish(subject, message)``."""
    week = due(store, settings, now)
    if week is None and not force:
        return {"ok": True, "sent": False}
    report = build(store, settings, now)
    publish("Superkugel: Wochenbericht", render(report))
    if week:
        store.put_item("OPS", f"REPORT#{week}", {"sent": True}, ttl_s=REPORT_TTL_S)
    log("weekly_report_sent", sessions=report["sessions"], cost_week_usd=report["cost_week_usd"])
    return {"ok": True, "sent": True}


def sns_publisher(topic_arn: str, region: str) -> Any:
    import boto3

    from superkugel.services.storage import fast_aws_config

    client = boto3.client("sns", region_name=region, config=fast_aws_config())
    return lambda subject, message: client.publish(TopicArn=topic_arn, Subject=subject[:99], Message=message)
