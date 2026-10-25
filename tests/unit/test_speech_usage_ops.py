from __future__ import annotations

import datetime as dt

from superkugel.config import ALEXA_VOICES, Settings
from superkugel.services.ops import CircuitBreaker, Mode, ParameterSource
from superkugel.services.storage import MemoryStore
from superkugel.services.usage import TokenUsage, UsageGuard, estimate_cost_usd
from superkugel.speech.ssml import MAX_SPEECH_CHARS, clean_text, limit_length, to_ssml


# --- SSML ----------------------------------------------------------------
def test_ssml_escapes_and_wraps_voice() -> None:
    s = to_ssml("Tom & Jerry <script>. Zweiter Satz!", voice="Vicki", rate="95%")
    assert "&amp;" in s and "&lt;script&gt;" in s
    assert s.startswith('<speak><voice name="Vicki"><lang xml:lang="de-DE"><prosody rate="95%">')
    assert '<break time="350ms"/>' in s


def test_ssml_no_pause_inside_date() -> None:
    s = to_ssml("Morgen, am Montag, dem 26. Oktober, regnet es. Dann Sonne.", voice="Vicki", rate="100%")
    assert "26. Oktober" in s and s.count("<break") == 1


def test_ssml_default_voice_has_no_voice_tag() -> None:
    assert "<voice" not in to_ssml("Hallo.", voice="alexa", rate="100%")
    assert 'rate="85%"' in to_ssml("Hallo.", slow=True)


def test_clean_text_removes_markdown_and_links() -> None:
    assert clean_text("**Wichtig**: siehe https://x.at\n- Punkt") == "Wichtig: siehe Punkt"


def test_limit_length_cuts_at_sentence() -> None:
    text = "Ein Satz. " * 400
    out = limit_length(text)
    assert len(out) <= MAX_SPEECH_CHARS and out.endswith(".")


def test_only_documented_alexa_voices_allowed(monkeypatch) -> None:
    monkeypatch.setenv("ALEXA_VOICE", "Hannah")  # Polly de-AT – laut Alexa-Doku nicht verfügbar
    assert Settings.from_env().voice == "alexa"
    monkeypatch.setenv("ALEXA_VOICE", "Marlene")
    assert Settings.from_env().voice == "Marlene"
    assert set(ALEXA_VOICES) == {"alexa", "Vicki", "Marlene", "Hans"}


# --- Kosten --------------------------------------------------------------
def test_cost_estimate() -> None:
    s = Settings(price_input_per_m=0.10, price_cached_input_per_m=0.01, price_output_per_m=0.50)
    cost = estimate_cost_usd(TokenUsage(input_tokens=1_000_000, cached_input_tokens=500_000, output_tokens=100_000), s)
    assert round(cost, 6) == round(0.05 + 0.005 + 0.05, 6)


def test_usage_limit_daily_and_monthly() -> None:
    store = MemoryStore()
    s = Settings(daily_cost_limit_usd=0.01, monthly_cost_limit_usd=1.0)
    guard = UsageGuard(store, s)
    now = dt.datetime(2026, 10, 24, tzinfo=dt.UTC)
    assert not guard.limit_reached(now)
    guard.record(TokenUsage(input_tokens=50_000, output_tokens=10_000), 800, now)  # 0.005 + 0.005
    assert guard.limit_reached(now)
    assert not guard.limit_reached(now + dt.timedelta(days=1))  # neuer Tag
    assert store.get_usage("MONTH#2026-10").requests == 1


def test_usage_read_error_does_not_block() -> None:
    class Broken(MemoryStore):
        def get_usage(self, period_key):
            raise RuntimeError("dynamo weg")

    assert not UsageGuard(Broken(), Settings()).limit_reached()


# --- Circuit-Breaker und Modus -------------------------------------------
def test_circuit_opens_after_threshold_and_recovers() -> None:
    t = [1000.0]
    cb = CircuitBreaker(MemoryStore(), Settings(circuit_failure_threshold=3, circuit_open_s=300), clock=lambda: t[0])
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()
    cb.record_failure()
    assert cb.is_open()
    t[0] += 301
    assert not cb.is_open()
    cb.record_failure()
    cb.record_success()
    assert cb.store.get_circuit() == {"failures": 0, "open_until": 0}


class FakeSSM:
    def __init__(self, values: dict[str, str] | None = None, fail: bool = False) -> None:
        self.values, self.fail, self.calls = values or {}, fail, 0

    def get_parameter(self, Name: str, WithDecryption: bool = False):
        self.calls += 1
        if self.fail:
            raise RuntimeError("ssm down")
        return {"Parameter": {"Value": self.values[Name]}}


def test_mode_cached_and_defaults_to_normal_on_error() -> None:
    t = [0.0]
    ssm = FakeSSM({"/superkugel/mode": "maintenance"})
    src = ParameterSource(Settings(mode_cache_s=60), ssm, clock=lambda: t[0])
    assert src.mode() is Mode.MAINTENANCE
    assert src.mode() is Mode.MAINTENANCE and ssm.calls == 1
    assert ParameterSource(Settings(), FakeSSM(fail=True)).mode() is Mode.NORMAL
    assert ParameterSource(Settings(), FakeSSM({"/superkugel/mode": "quatsch"})).mode() is Mode.NORMAL


def test_api_key_from_ssm_and_missing() -> None:
    src = ParameterSource(Settings(), FakeSSM({"/superkugel/openai-api-key": " sk-abc "}))
    assert src.openai_api_key() == "sk-abc"
    assert ParameterSource(Settings(), FakeSSM(fail=True)).openai_api_key() is None


def test_api_key_reloaded_after_invalidate() -> None:
    ssm = FakeSSM({"/superkugel/openai-api-key": "alt"})
    src = ParameterSource(Settings(), ssm)
    assert src.openai_api_key() == "alt"
    ssm.values["/superkugel/openai-api-key"] = "neu"
    assert src.openai_api_key() == "alt"  # gecacht
    src.invalidate_api_key()
    assert src.openai_api_key() == "neu"


def test_sie_texts_never_use_du_form() -> None:
    import re

    from superkugel.speech.texts import TEXTS, text

    du_words = re.compile(r"\b(du|dir|dich|dein|deine|deiner|magst|hast|sag's|fang|frag|ruf)\b", re.IGNORECASE)
    for key, (_du, sie) in TEXTS.items():
        # „Sag mal …“ ist ein Beispielsatz für die Nutzerin, keine Anrede
        assert not du_words.search(sie.replace("Sag mal", "")), key
    assert "Sie" in text("sie", "fallback") and "Du" in text("du", "fallback")


def test_launch_uses_configured_address_form() -> None:
    from conftest import launch, make_harness, speech

    assert "Servus" in speech(make_harness(Settings(address_form="du", progressive_after_s=5)).send(launch()))
    assert "Grüß Gott" in speech(make_harness(Settings(address_form="sie", progressive_after_s=5)).send(launch()))


def test_region_ascii_spelling_is_normalized(monkeypatch) -> None:
    monkeypatch.setenv("USER_REGION", "Kaernten")
    assert Settings.from_env().user_region == "Kärnten"
