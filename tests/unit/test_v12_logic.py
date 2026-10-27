"""v1.2 – reine Logik: Zahlwörter, Erinnerungs-Zeiten, Reminders-API, Radio, Morgengruß, Rätsel, Wochenbericht."""

from __future__ import annotations

import datetime as dt
import itertools
import json
import random
from zoneinfo import ZoneInfo

import pytest

from superkugel.config import Settings
from superkugel.features import morning
from superkugel.language import numbers_in, word_to_int
from superkugel.quiz import engine
from superkugel.quiz.items import BY_ID, ITEMS
from superkugel.radio import stations
from superkugel.reminders import parse
from superkugel.reminders.api import ReminderApi, ReminderError
from superkugel.services import report
from superkugel.services.storage import MemoryStore
from superkugel.speech.texts import text as t_text

VIE = ZoneInfo("Europe/Vienna")


def vienna(y: int, mo: int, d: int, h: int, mi: int = 0) -> dt.datetime:
    return dt.datetime(y, mo, d, h, mi, tzinfo=VIE)


# ------------------------------------------------------------------ Zahlwörter
@pytest.mark.parametrize(("word", "value"), [
    ("zehn", 10), ("einundzwanzig", 21), ("dreißig", 30), ("dreissig", 30), ("fünfundsiebzig", 75),
    ("hundert", 100), ("zweihundertzwölf", 212), ("12", 12), ("zwölf", 12), ("null", 0), ("Hund", None),
])
def test_word_to_int(word: str, value: int | None) -> None:
    assert word_to_int(word) == value


def test_numbers_in_sentence_ignores_article_ein() -> None:
    assert numbers_in("ich glaube es sind ein paar, also sieben") == [7]


# ------------------------------------------------------------------ Erinnerungen: Zeitauflösung
NOW = vienna(2026, 10, 27, 9, 0)  # Dienstag, 9:00 Wien (Winterzeit, UTC+1)


def _resolve(text: str, now: dt.datetime = NOW) -> tuple[parse.Draft, parse.Resolved | None]:
    d = parse.parse(text, now)
    return d, parse.resolve(d, now)


def test_tomorrow_at_ten_with_content() -> None:
    d, r = _resolve("morgen um zehn an den Arzt")
    assert d.text == "den Arzt" and r and r.when == vienna(2026, 10, 28, 10) and not r.in_past
    assert parse.spoken_when(r.when, NOW) == "morgen, Mittwoch, um 10 Uhr"


def test_today_relative_hour() -> None:
    d, r = _resolve("in einer Stunde an die Wäsche")
    assert r and r.when == vienna(2026, 10, 27, 10) and d.text == "die Wäsche"


@pytest.mark.parametrize(("phrase", "hour", "minute"), [
    ("um halb drei", 14, 30), ("um dreiviertel zehn", 9, 45), ("um viertel nach zehn", 10, 15),
    ("um viertel vor zwölf", 11, 45), ("um 14 uhr", 14, 0), ("um zehn uhr dreißig", 10, 30),
    ("um 10:30", 10, 30), ("abends um sieben", 19, 0), ("in der früh um acht", 8, 0),
])
def test_clock_phrases(phrase: str, hour: int, minute: int) -> None:
    _, r = _resolve(f"morgen {phrase} an den Bus")
    assert r and (r.when.hour, r.when.minute) == (hour, minute)


def test_without_date_passed_time_becomes_evening_or_rejected() -> None:
    _, r = _resolve("um acht an den Film")  # 9:00 → 20:00 heute
    assert r and r.when == vienna(2026, 10, 27, 20) and not r.in_past
    _, r2 = _resolve("heute um sieben in der früh an den Film")
    assert r2 and r2.in_past  # ausdrücklich früh und vorbei → ablehnen


def test_missing_time_and_missing_text() -> None:
    d, r = _resolve("an den Arzt")
    assert d.text == "den Arzt" and r is None
    d2, r2 = _resolve("morgen um zehn")
    assert d2.text is None and r2 and r2.when.hour == 10


def test_weekday_and_date_phrases() -> None:
    _, r = _resolve("am Dienstag um neun an den Friseur")  # heute ist Dienstag → nächste Woche
    assert r and r.when.date() == dt.date(2026, 11, 3)
    _, r = _resolve("am dritten november um 9 an den Friseur")
    assert r and r.when.date() == dt.date(2026, 11, 3)
    _, r = _resolve("am 3. november um 14 uhr an die Karte")
    assert r and r.when == vienna(2026, 11, 3, 14)


def test_midnight_vienna_not_utc_date() -> None:
    late = vienna(2026, 10, 27, 23, 30)  # in UTC schon 22:30 – „morgen“ ist trotzdem der 28. in Wien
    _, r = _resolve("morgen um neun an die Post", late)
    assert r and r.when == vienna(2026, 10, 28, 9)
    _, r = _resolve("um mitternacht an das Feuerwerk", NOW)
    assert r and r.when == vienna(2026, 10, 28, 0)


def test_daylight_saving_switch_keeps_local_hour() -> None:
    before_spring = vienna(2026, 3, 28, 12)  # Umstellung in der Nacht auf 29.3.
    _, r = _resolve("morgen um zehn an die Messe", before_spring)
    assert r and r.when.utcoffset() == dt.timedelta(hours=2) and r.when.hour == 10
    before_autumn = vienna(2026, 10, 24, 12)  # Umstellung in der Nacht auf 25.10.
    _, r = _resolve("morgen um zehn an die Messe", before_autumn)
    assert r and r.when.utcoffset() == dt.timedelta(hours=1) and r.when.hour == 10


def test_relative_across_midnight_and_minutes() -> None:
    late = vienna(2026, 10, 27, 23, 40)
    _, r = _resolve("in einer halben Stunde an den Herd", late)
    assert r and r.when == vienna(2026, 10, 28, 0, 10)
    _, r = _resolve("in zwanzig Minuten an den Kuchen")
    assert r and r.when == vienna(2026, 10, 27, 9, 20)


def test_from_slots() -> None:
    d = parse.from_slots("2026-10-29", "15:00", "", NOW)
    assert (d.date, d.time) == ("2026-10-29", "15:00")
    d = parse.from_slots("", "", "PT1H30M", NOW)
    assert (d.date, d.time) == ("2026-10-27", "10:30")
    d = parse.from_slots("2026-10-29", "MO", "", NOW)
    assert d.time == "08:00"
    r = parse.resolve(parse.from_slots("2026-10-29", "03:00", "", NOW), NOW)
    assert r and r.when.hour == 15  # „um drei“ ohne Tageszeit = Nachmittag


# ------------------------------------------------------------------ Reminders-API
class FakeTransport:
    def __init__(self, *responses: tuple[int, object] | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "body": json.loads(body) if body else None, "timeout": timeout})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        code, data = r
        return code, json.dumps(data).encode() if data is not None else b""


def test_create_payload_local_time_with_timezone() -> None:
    tr = FakeTransport((201, {"alertToken": "a1"}))
    api = ReminderApi("https://api.eu.amazonalexa.com", "tok", "Europe/Vienna", transport=tr)
    assert api.create(vienna(2026, 10, 28, 10), "den arzt", NOW) == "a1"
    call = tr.calls[0]
    assert call["method"] == "POST" and call["url"] == "https://api.eu.amazonalexa.com/v1/alerts/reminders"
    assert call["headers"]["Authorization"] == "Bearer tok" and call["timeout"] <= 3.0
    trig = call["body"]["trigger"]
    assert trig == {"type": "SCHEDULED_ABSOLUTE", "scheduledTime": "2026-10-28T10:00:00.000", "timeZoneId": "Europe/Vienna"}
    assert call["body"]["alertInfo"]["spokenInfo"]["content"] == [{"locale": "de-DE", "text": "den arzt"}]


@pytest.mark.parametrize(("status", "code", "kind"), [
    (401, "UNAUTHORIZED", "permission"), (403, "MAX_REMINDERS_EXCEEDED", "limit"),
    (403, "DEVICE_NOT_SUPPORTED", "unsupported"), (400, "TRIGGER_SCHEDULED_TIME_IN_PAST", "past"),
    (500, "", "failed"), (429, "", "failed"),
])
def test_error_mapping(status: int, code: str, kind: str) -> None:
    api = ReminderApi("https://api.eu.amazonalexa.com", "tok", "Europe/Vienna",
                      transport=FakeTransport((status, {"code": code})))
    with pytest.raises(ReminderError) as exc:
        api.create(vienna(2026, 10, 28, 10), "x", NOW)
    assert exc.value.kind == kind


def test_timeout_is_failed_and_foreign_host_rejected() -> None:
    api = ReminderApi("https://api.eu.amazonalexa.com", "tok", "Europe/Vienna",
                      transport=FakeTransport(ReminderError("failed")))
    with pytest.raises(ReminderError):
        api.list()
    for bad in ("https://evil.example.com", "http://api.eu.amazonalexa.com", ""):
        with pytest.raises(ReminderError):
            ReminderApi(bad, "tok", "Europe/Vienna")


def test_list_filters_and_sorts() -> None:
    alerts = {"alerts": [
        {"alertToken": "b", "status": "ON", "trigger": {"scheduledTime": "2026-10-30T09:00:00.000", "timeZoneId": "Europe/Vienna"},
         "alertInfo": {"spokenInfo": {"content": [{"locale": "de-DE", "text": "später"}]}}},
        {"alertToken": "a", "status": "ON", "trigger": {"scheduledTime": "2026-10-28T09:00:00.000"},
         "alertInfo": {"spokenInfo": {"content": [{"locale": "de-DE", "text": "früher"}]}}},
        {"alertToken": "c", "status": "COMPLETED", "trigger": {}, "alertInfo": {}},
    ]}
    api = ReminderApi("https://api.amazonalexa.com", "tok", "Europe/Vienna", transport=FakeTransport((200, alerts)))
    got = api.list()
    assert [r.token for r in got] == ["a", "b"] and got[0].when == vienna(2026, 10, 28, 9)


# ------------------------------------------------------------------ Radio
def test_station_synonyms_and_region() -> None:
    s = Settings(user_region="Kärnten")
    assert stations.stations(s)[0].station_id == "ktn"
    for said, sid in [("Ö eins", "oe1"), ("ö1", "oe1"), ("Radio Kärnten", "ktn"), ("Kärnten heute", "ktn"),
                      ("FM vier", "fm4"), ("hitradio ö3", "oe3"), ("den Sender Ö drei", "oe3")]:
        st = stations.match(said, s)
        assert st and st.station_id == sid, said
    assert stations.match("Radio Wien", s) is None  # nur das eigene Bundesland
    assert stations.match("Mord im Kräuterbeet", s) is None
    assert all(st.url.startswith("https://") for st in stations.stations(s))


def test_radio_token_never_parses_as_book() -> None:
    from superkugel.audiobooks import player

    token = stations.token_for(stations.NATIONAL[0])
    assert token.startswith("radio-") and player.parse_token(token) is None


def test_health_check_and_down_logic() -> None:
    store, s = MemoryStore(), Settings(user_region="Kärnten")
    probe = lambda url, timeout: (200, "audio/mpeg") if "oe1" not in url else (404, "text/html")  # noqa: E731
    down = stations.check_health(store, s, prober=probe, clock=lambda: 1000.0)
    assert down == ["oe1"]
    oe1, oe3 = stations.by_id("oe1", s), stations.by_id("oe3", s)
    assert stations.is_down(store, oe1, s, clock=lambda: 1100.0)
    assert not stations.is_down(store, oe3, s, clock=lambda: 1100.0)
    assert not stations.is_down(store, oe1, s, clock=lambda: 1000.0 + 4 * 3600)  # Prüfung zu alt
    stations.check_health(store, s, prober=lambda u, t: (_ for _ in ()).throw(OSError()), clock=lambda: 2000.0)
    assert not stations.is_down(store, oe1, s, clock=lambda: 2100.0)  # alle tot → Prüfproblem → trotzdem spielen


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


# ------------------------------------------------------------------ Rätsel
def test_quiz_collection_size_and_self_consistency() -> None:
    assert len(ITEMS) >= 60 and len(BY_ID) == len(ITEMS)
    assert {i.kind for i in ITEMS} == {"spruch", "wissen", "rechnen"}
    for item in ITEMS:
        assert item.answers and item.hint and item.question
        for a in item.answers:
            assert engine.is_correct(item, a), (item.item_id, a)


@pytest.mark.parametrize(("item_id", "said", "ok"), [
    ("s01", "Gold im Mund", True), ("s01", "ich glaube gold", True), ("s01", "GOLD IM MUND!", True),
    ("s01", "Silber", False), ("w02", "der grossglockner", True), ("w02", "Großklockner", True),
    ("w02", "Dachstein", False), ("w15", "erdaepfel", True), ("w03", "neun", True), ("w03", "es sind 9", True),
    ("w03", "acht", False), ("r15", "fünfundsiebzig", True), ("r15", "75", True), ("r15", "siebzig", False),
    ("w09", "rot weiß rot", True), ("w01", "das ist klagenfurt", True),
])
def test_quiz_tolerant_check(item_id: str, said: str, ok: bool) -> None:
    assert engine.is_correct(BY_ID[item_id], said) is ok


def test_quiz_give_up_and_explain() -> None:
    assert engine.gives_up("weiß nicht") and engine.gives_up("keine Ahnung") and engine.gives_up("sag's mir")
    assert not engine.gives_up("Gold im Mund")
    assert engine.wants_explanation("erklär mir das")


def test_quiz_no_repeat_within_seven_days() -> None:
    today = dt.date(2026, 10, 27)
    rng = random.Random(1)
    seen: dict[str, str] = {}
    asked = []
    for _ in range(len(ITEMS)):
        item = engine.pick(seen, today, asked[-1].kind if asked else None, rng)
        assert item is not None and item.item_id not in seen
        seen[item.item_id] = today.isoformat()
        asked.append(item)
    assert {i.item_id for i in asked} == {i.item_id for i in ITEMS}
    assert all(a.kind != b.kind for a, b in itertools.pairwise(asked[:21]))  # gemischt
    old = {k: (today - dt.timedelta(days=7)).isoformat() for k in seen}
    assert engine.pick(old, today, None, rng).item_id in seen  # nach 7 Tagen wieder erlaubt
    six = {k: (today - dt.timedelta(days=6)).isoformat() for k in seen}
    gen = engine.pick(six, today, None, rng)  # Sammlung aufgebraucht → frisch erzeugte Rechnung, nie leer
    assert gen is not None and gen.item_id.startswith("g") and gen.kind == "rechnen"
    assert engine.item(gen.item_id) == gen and engine.is_correct(gen, gen.answers[0])


@pytest.mark.parametrize(("item_id", "said"), [
    ("w12", "siebzehn"), ("s14", "Eile"), ("s32", "rastet"), ("s31", "Laute"), ("s09", "lange Beine"),
    ("s20", "beißen immer"), ("w15", "Äpfel"),
])
def test_quiz_rejects_review_false_positives(item_id: str, said: str) -> None:
    assert not engine.is_correct(BY_ID[item_id], said)


def test_quiz_split_number_words() -> None:
    assert engine.is_correct(BY_ID["r15"], "fünf und siebzig")


# ------------------------------------------------------------------ Wochenbericht
FORBIDDEN = ("Geheimtitel", "Arzt", "Maria", "Teststadt", "Schlagzeile", "Wurstsemmel", "Kärnten")


def _report_store() -> MemoryStore:
    from conftest import book

    store = MemoryStore()
    store.put_book(book(book_id="neu", title="Geheimtitel", imported_at="2026-10-22T10:00:00+00:00"))
    store.put_book(book(book_id="alt", title="Geheimtitel 2", imported_at="2026-01-01T10:00:00+00:00"))
    store.put_conversation("u", {"turns": [{"role": "user", "content": "Wurstsemmel beim Arzt, Maria"}]}, 600)
    store.put_item("CONTEXT", "CURRENT", {"region": "Kärnten", "news": {"value": ["Schlagzeile"], "at": 1000.0}})
    store.put_item("RADIO", "HEALTH", {"down": ["fm4"], "checked": 4, "at": 1000.0})
    for day, n in (("2026-10-19", 2), ("2026-10-25", 3), ("2026-10-26", 99)):  # 26. = Berichtstag (Montag)
        store.add_stats(day, {"sessions": n, "radio": 1, "errors": 1}, 3600)
    store.add_usage("2026-10-20", "2026-10", 1000, 100, 2500, searches=1)
    return store


def test_report_contains_only_numbers() -> None:
    store = _report_store()
    now = vienna(2026, 10, 26, 8, 5)
    r = report.build(store, Settings(user_name="Maria", user_city="Teststadt", user_region="Kärnten"), now,
                     clock=1000.0 + 7200)
    assert (r["week_from"], r["week_to"]) == ("2026-10-19", "2026-10-25")
    assert r["sessions"] == 5 and r["radio"] == 2 and r["errors"] == 2 and r["chat_requests"] == 1
    assert r["web_searches"] == 1 and r["new_audiobooks"] == 1 and r["context_age_h"] == 2.0
    assert r["radio_down"] == ["fm4"]
    assert set(r) <= report.ALLOWED_KEYS
    for k, v in r.items():
        assert isinstance(v, int | float | type(None)) or k in ("week_from", "week_to", "radio_down", "month"), k
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
@pytest.mark.parametrize(("now", "phrase", "expected"), [
    (vienna(2026, 10, 27, 0, 30), "in einer Stunde an die Tabletten", vienna(2026, 10, 27, 1, 30)),
    (vienna(2026, 10, 27, 4, 30), "in einer Stunde an X", vienna(2026, 10, 27, 5, 30)),
    (vienna(2026, 10, 27, 21, 30), "um sieben in der früh an X", vienna(2026, 10, 28, 7)),
    (vienna(2026, 10, 27, 21, 30), "um acht an die Tabletten", vienna(2026, 10, 28, 8)),
    (NOW, "in zwei Tagen um zehn an den Arzt", vienna(2026, 10, 29, 10)),
    (NOW, "morgen um ein Uhr nachts an X", vienna(2026, 10, 28, 1)),
    (NOW, "heute um elf in der nacht an X", vienna(2026, 10, 27, 23)),
    (NOW, "um zwölf in der nacht an X", vienna(2026, 10, 28, 0)),
    (NOW, "um zehn nach drei an X", vienna(2026, 10, 27, 15, 10)),
    (NOW, "um fünf vor acht an X", vienna(2026, 10, 27, 19, 55)),
    (NOW, "um 24 uhr an X", vienna(2026, 10, 28, 0)),
    (NOW, "in eineinhalb stunden an X", vienna(2026, 10, 27, 10, 30)),
    (NOW, "am 3. jänner um 9 an X", vienna(2027, 1, 3, 9)),
])
def test_review_time_cases(now: dt.datetime, phrase: str, expected: dt.datetime) -> None:
    _, r = _resolve(phrase, now)
    assert r and r.when == expected and not r.in_past


def test_relative_time_in_fall_back_night_is_real_duration() -> None:
    now = vienna(2026, 10, 25, 1, 30)  # 01:30 Sommerzeit = 23:30 UTC
    _, r = _resolve("in zwei Stunden an X", now)
    assert r and r.when - now.astimezone(dt.UTC) == dt.timedelta(hours=2)
    d = parse.from_slots("", "", "PT1H", vienna(2026, 10, 27, 0, 30))
    assert parse.resolve(d, vienna(2026, 10, 27, 0, 30)).when == vienna(2026, 10, 27, 1, 30)


def test_week_and_leap_day_and_year_spoken() -> None:
    d, r = _resolve("in einer Woche an X")
    assert d.date == "2026-11-03" and r is None  # Uhrzeit wird nachgefragt
    _, r = _resolve("am 29. februar um 9 an X")
    assert r and r.when.date() == dt.date(2028, 2, 29)
    assert "2028" in parse.spoken_when(r.when, NOW)


def test_api_never_follows_redirects_and_unknown_zone() -> None:
    from superkugel.reminders import api as api_mod

    assert api_mod._NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example") is None
    alerts = {"alerts": [{"alertToken": "a", "status": "ON",
                          "trigger": {"scheduledTime": "2026-10-28T09:00:00.000", "timeZoneId": "Mars/Olympus"},
                          "alertInfo": {"spokenInfo": {"content": [{"text": "x"}]}}}]}
    api = ReminderApi("https://api.eu.amazonalexa.com", "t", "Europe/Vienna", transport=FakeTransport((200, alerts)))
    assert api.list()[0].when is None


def test_more_distressing_headlines_filtered() -> None:
    for h in ("Doppelmord in Graz", "Bergsteiger tödlich verunglückt", "Frau kam ums Leben", "Bluttat im Ort"):
        assert morning.is_distressing(h), h


def test_report_month_is_month_of_report_week() -> None:
    store = MemoryStore()
    store.add_usage("2026-10-30", "2026-10", 1, 1, 1_500_000)
    r = report.build(store, Settings(), vienna(2026, 11, 2, 8), clock=0.0)
    assert r["cost_month_usd"] == 1.5
