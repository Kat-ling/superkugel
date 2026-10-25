"""Zentrale Konfiguration. Alle Werte kommen aus Umgebungsvariablen (siehe .env.example)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


SPEECH_STYLES = ("kaernten", "bayern", "standard")
# Laut Alexa-SSML-Referenz für de-DE erlaubte <voice>-Namen (Stand Okt. 2026).
# "alexa" = Standardstimme ohne <voice>-Tag.
ALEXA_VOICES = ("alexa", "Vicki", "Marlene", "Hans")


@dataclass(frozen=True)
class Settings:
    skill_id: str = ""
    table_name: str = "superkugel"
    audio_bucket: str = ""
    aws_region: str = "eu-north-1"

    # OpenAI
    openai_api_key_param: str = "/superkugel/openai-api-key"
    openai_api_key: str = ""  # nur lokal; in AWS kommt der Schlüssel aus SSM
    openai_model: str = "gpt-6-luna"
    openai_reasoning_effort: str = "none"
    openai_base_url: str = "https://api.openai.com/v1"
    max_output_tokens: int = 350
    # Preise in USD pro 1 Mio. Tokens (für die Kostenschätzung, nicht für Abrechnung)
    price_input_per_m: float = 0.10
    price_cached_input_per_m: float = 0.01
    price_output_per_m: float = 0.50

    # Zeitbudget. Alexa wartet ca. 8 s auf die vollständige Antwort.
    request_deadline_s: float = 7.2
    llm_timeout_s: float = 6.5
    # Lückenfüller („Moment …“) erst, wenn die KI so lange braucht; kurze Pausen bleiben still.
    progressive_after_s: float = 4.5

    # Gesprächsspeicher
    history_max_turns: int = 8
    history_max_chars: int = 6000
    resume_window_s: int = 30 * 60

    # Kostenschranken (echte Sperren im Skill)
    daily_cost_limit_usd: float = 0.50
    monthly_cost_limit_usd: float = 8.00
    circuit_failure_threshold: int = 3
    circuit_open_s: int = 300

    # Betriebsmodus (Fernschalter)
    mode_param: str = "/superkugel/mode"
    mode_cache_s: int = 60

    # Sprache
    speech_style: str = "kaernten"
    voice: str = "alexa"
    speech_rate: str = "100%"
    address_form: str = "sie"  # "du" oder "sie"
    user_name: str = ""  # Vorname der Nutzerin, z. B. "Maria" (leer = keine Namensnennung)
    misunderstood_limit: int = 5  # so oft „nicht verstanden“, bevor sich der Skill verabschiedet

    # Hörbuch
    audio_url_expiry_s: int = 6 * 3600
    rewind_s: int = 30
    forward_s: int = 30
    max_playback_retries: int = 2

    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Settings:
        style = _env("SPEECH_STYLE", "kaernten").lower()
        voice = _env("ALEXA_VOICE", "alexa")
        return cls(
            skill_id=_env("SKILL_ID", ""),
            table_name=_env("TABLE_NAME", "superkugel"),
            audio_bucket=_env("AUDIO_BUCKET", ""),
            aws_region=_env("AWS_REGION", "eu-north-1"),
            openai_api_key_param=_env("OPENAI_API_KEY_PARAM", "/superkugel/openai-api-key"),
            openai_api_key=_env("OPENAI_API_KEY", ""),
            openai_model=_env("OPENAI_MODEL", "gpt-6-luna"),
            openai_reasoning_effort=_env("OPENAI_REASONING_EFFORT", "none"),
            openai_base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            max_output_tokens=_int("MAX_OUTPUT_TOKENS", 350),
            price_input_per_m=_float("PRICE_INPUT_PER_M", 0.10),
            price_cached_input_per_m=_float("PRICE_CACHED_INPUT_PER_M", 0.01),
            price_output_per_m=_float("PRICE_OUTPUT_PER_M", 0.50),
            request_deadline_s=_float("REQUEST_DEADLINE_S", 7.2),
            llm_timeout_s=_float("LLM_TIMEOUT_S", 6.5),
            progressive_after_s=_float("PROGRESSIVE_AFTER_S", 4.5),
            history_max_turns=_int("HISTORY_MAX_TURNS", 8),
            history_max_chars=_int("HISTORY_MAX_CHARS", 6000),
            resume_window_s=_int("RESUME_WINDOW_S", 1800),
            daily_cost_limit_usd=_float("DAILY_COST_LIMIT_USD", 0.50),
            monthly_cost_limit_usd=_float("MONTHLY_COST_LIMIT_USD", 8.00),
            circuit_failure_threshold=_int("CIRCUIT_FAILURE_THRESHOLD", 3),
            circuit_open_s=_int("CIRCUIT_OPEN_S", 300),
            mode_param=_env("MODE_PARAM", "/superkugel/mode"),
            mode_cache_s=_int("MODE_CACHE_S", 60),
            speech_style=style if style in SPEECH_STYLES else "standard",
            voice=voice if voice in ALEXA_VOICES else "alexa",
            speech_rate=_env("SPEECH_RATE", "100%"),
            address_form="du" if _env("ADDRESS_FORM", "sie").lower() == "du" else "sie",
            user_name=re.sub(r"[^\w\- ]", "", _env("USER_NAME", ""))[:40].strip(),
            misunderstood_limit=max(2, _int("MISUNDERSTOOD_LIMIT", 5)),
            audio_url_expiry_s=_int("AUDIO_URL_EXPIRY_S", 6 * 3600),
            rewind_s=_int("REWIND_S", 30),
            forward_s=_int("FORWARD_S", 30),
            max_playback_retries=_int("MAX_PLAYBACK_RETRIES", 2),
        )
