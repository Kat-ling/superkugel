"""Reine Logik: Morgengruß und Wochenbericht (seit 1.2)."""

from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

from superkugel.config import Settings
from superkugel.features import morning
from superkugel.services import report
from superkugel.services.storage import MemoryStore
from superkugel.speech.texts import text as t_text

VIE = ZoneInfo("Europe/Vienna")


def vienna(y: int, mo: int, d: int, h: int, mi: int = 0) -> dt.datetime:
    return dt.datetime(y, mo, d, h, mi, tzinfo=VIE)


# ------------------------------------------------------------------ Morgengruß
def _ctx(at: float, regional=("Lawine fordert zwei Tote", "Neue Brücke über die Drau eröffnet"),
         news=("Tödlicher Unfall auf der A2", "Nationalrat beschließt Budget", "Wetter bleibt mild")) -> dict:
    return {"news": {"value": list(news), "at": at}, "regional": {"value": list(regional), "at": at},
            "weather": {"value": [{"date": "2026-10-27", "min": 3.4, "max": 14.6, "rain": 70, "desc": "teils bewölkt"}],
                        "at": at}}


def _t(key: str, **kw: object) -> str:
    return t_text("du", key, **kw)


def test_morning_compose_filters_and_formats() -> None:
    local = vienna(2026, 10, 27, 8)
    out = morning.compose(_t, Settings(), _ctx(local.timestamp()), local, local.timestamp(), "Maria")
    assert out.startswith("Guten Morgen, Maria! Heute ist Dienstag, der 27. Oktober.")
    assert "teils bewölkt, 3 bis 15 Grad" in out and "Schirm" in out
    assert "Neue Brücke über die Drau eröffnet" in out and "Nationalrat beschließt Budget" in out
    assert "Tote" not in out and "Unfall" not in out


def test_morning_drops_stale_parts() -> None:
    local = vienna(2026, 10, 27, 8)
    old = local.timestamp() - 7 * 3600  # älter als CONTEXT_MAX_AGE_H (6 h)
    out = morning.compose(_t, Settings(), _ctx(old), local, local.timestamp(), "")
    assert out == "Guten Morgen! Heute ist Dienstag, der 27. Oktober."
    assert morning.compose(_t, Settings(), None, local, local.timestamp(), "").startswith("Guten Morgen!")


def test_distress_word_list() -> None:
    for h in ("Mordprozess in Graz", "Verkehrsunfall bei Spittal", "Großbrand in Halle", "Krieg in Nahost",
              "Zwei Verletzte nach Explosion"):
        assert morning.is_distressing(h), h
    for h in ("Neuer Kindergarten eröffnet", "Kärntner Seen so warm wie nie", "Wahl: Ergebnis steht fest"):
        assert not morning.is_distressing(h), h


def test_morning_window_once_per_day_and_switches() -> None:
    store, s = MemoryStore(), Settings()
    assert not morning.should_greet(store, s, "u", vienna(2026, 10, 27, 4, 59))
    assert morning.should_greet(store, s, "u", vienna(2026, 10, 27, 5, 0))
    assert not morning.should_greet(store, s, "u", vienna(2026, 10, 27, 9))  # schon begrüßt
    assert morning.should_greet(store, s, "other-device", vienna(2026, 10, 27, 9))  # pro Gerät
    assert not morning.should_greet(store, s, "u2", vienna(2026, 10, 27, 11, 0))
    assert morning.should_greet(store, s, "u", vienna(2026, 10, 28, 10, 59))  # neuer Tag
    morning.set_enabled(store, "u", False)
    assert not morning.should_greet(store, s, "u", vienna(2026, 10, 29, 8))
    assert not morning.should_greet(MemoryStore(), Settings(morning_briefing=False), "u", vienna(2026, 10, 27, 8))
    flags = store.get_item("USER#u", "DAYFLAGS")
    assert flags and "expires_at" in flags  # Tagesmerker mit TTL, kein Verlauf


# ------------------------------------------------------------------ Wochenbericht
FORBIDDEN = ("Geheimtitel", "Arzt", "Maria", "Teststadt", "Schlagzeile", "Wurstsemmel", "Kärnten")


def _report_store() -> MemoryStore:
    from conftest import book

    store = MemoryStore()
    store.put_book(book(book_id="neu", title="Geheimtitel", imported_at="2026-10-22T10:00:00+00:00"))
    store.put_book(book(book_id="alt", title="Geheimtitel 2", imported_at="2026-01-01T10:00:00+00:00"))
    store.put_conversation("u", {"turns": [{"role": "user", "content": "Wurstsemmel beim Arzt, Maria"}]}, 600)
    store.put_item("CONTEXT", "CURRENT", {"region": "Kärnten", "news": {"value": ["Schlagzeile"], "at": 1000.0}})
    for day, n in (("2026-10-19", 2), ("2026-10-25", 3), ("2026-10-26", 99)):  # 26. = Berichtstag (Montag)
        store.add_stats(day, {"sessions": n, "alexa_hint": 1, "errors": 1}, 3600)
    store.add_usage("2026-10-20", "2026-10", 1000, 100, 2500, searches=1)
    return store


def test_report_contains_only_numbers() -> None:
    store = _report_store()
    now = vienna(2026, 10, 26, 8, 5)
    r = report.build(store, Settings(user_name="Maria", user_city="Teststadt", user_region="Kärnten"), now,
                     clock=1000.0 + 7200)
    assert (r["week_from"], r["week_to"]) == ("2026-10-19", "2026-10-25")
    assert r["sessions"] == 5 and r["alexa_hint"] == 2 and r["errors"] == 2 and r["chat_requests"] == 1
    assert r["web_searches"] == 1 and r["new_audiobooks"] == 1 and r["context_age_h"] == 2.0
    assert set(r) <= report.ALLOWED_KEYS
    for k, v in r.items():
        assert isinstance(v, int | float | type(None)) or k in ("week_from", "week_to", "month"), k
    text = report.render(r)
    for word in FORBIDDEN:
        assert word not in text and word not in json.dumps(r, ensure_ascii=False), word


def test_report_due_once_per_week_and_only_at_eight() -> None:
    store, s = _report_store(), Settings()
    sent: list[tuple[str, str]] = []
    pub = lambda subj, msg: sent.append((subj, msg))  # noqa: E731
    assert report.send(store, s, pub, vienna(2026, 10, 26, 7, 0)) == {"ok": True, "sent": False}  # Sommer/Winter-Doppel
    assert report.send(store, s, pub, vienna(2026, 10, 26, 8, 0))["sent"]
    assert not report.send(store, s, pub, vienna(2026, 10, 26, 8, 30))["sent"]  # schon gesendet
    assert report.send(store, s, pub, vienna(2026, 10, 26, 13, 0), force=True)["sent"]
    assert len(sent) == 2 and sent[0][0] == "Superkugel: Wochenbericht"


def test_run_weekly_report_error_path(capsys) -> None:
    from conftest import make_harness
    from superkugel.app import run_weekly_report

    h = make_harness(Settings(alert_topic_arn=""))
    assert run_weekly_report(h.services, force=True) == {"ok": False}  # kein Thema → Fehler, kein Absturz
    out = capsys.readouterr().out
    assert "WeeklyReportFailed" in out and "weekly_report_failed" in out

    def boom(subject: str, message: str) -> None:
        raise RuntimeError("sns down")

    assert run_weekly_report(h.services, publish=boom, force=True) == {"ok": False}
    sent: list[str] = []
    assert run_weekly_report(h.services, publish=lambda s, m: sent.append(m), force=True)["sent"]


# ------------------------------------------------------------------ Regressionen aus den Reviews (27.10.2026)


def test_more_distressing_headlines_filtered() -> None:
    for h in ("Doppelmord in Graz", "Bergsteiger tödlich verunglückt", "Frau kam ums Leben", "Bluttat im Ort"):
        assert morning.is_distressing(h), h


def test_report_month_is_month_of_report_week() -> None:
    store = MemoryStore()
    store.add_usage("2026-10-30", "2026-10", 1, 1, 1_500_000)
    r = report.build(store, Settings(), vienna(2026, 11, 2, 8), clock=0.0)
    assert r["cost_month_usd"] == 1.5
