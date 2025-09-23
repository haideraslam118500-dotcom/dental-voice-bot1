from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from yaml import YAMLError, safe_load
from dotenv import load_dotenv


PRACTICE_CONFIG_PATH = Path("config/practice.yml")
FALLBACK_VOICE = "alice"
FALLBACK_LANGUAGE = "en-GB"

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class PracticeConfig:
    practice_name: str
    voice: Optional[str]
    language: Optional[str]
    hours: str
    address: str
    prices: str
    services: dict[str, str]


def _load_practice_config() -> PracticeConfig:
    defaults: dict[str, Any] = {
        "practice_name": "Oak Dental",
        "voice": "Polly.Amy",
        "language": "en-GB",
        "hours": (
            "We’re open Monday to Friday nine to five, Saturday nine to one. Closed Sundays and bank holidays."
        ),
        "address": "We’re at 12 High Street, Oakford, OX1 2AB. Entrance next to the pharmacy.",
        "prices": "A routine check-up is forty five pounds. Hygiene is sixty five. Whitening starts from two hundred and fifty.",
        "services": {
            "checkup": "Check-up is £45",
            "hygiene": "Hygiene is £65",
            "whitening": "Whitening starts from £250",
            "extraction": "Tooth extraction is £120",
        },
    }

    if PRACTICE_CONFIG_PATH.exists():
        try:
            loaded = safe_load(PRACTICE_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except OSError as exc:  # pragma: no cover - configuration read errors are rare
            raise RuntimeError(f"Unable to read practice configuration: {exc}") from exc
        except YAMLError as exc:  # pragma: no cover - invalid YAML should crash early
            raise RuntimeError(f"Invalid YAML in {PRACTICE_CONFIG_PATH}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise RuntimeError(
                f"Invalid YAML in {PRACTICE_CONFIG_PATH}: top-level document must be a mapping"
            )
        defaults.update({k: v for k, v in loaded.items() if v is not None})

    return PracticeConfig(
        practice_name=str(defaults.get("practice_name", "Oak Dental")),
        voice=defaults.get("voice"),
        language=defaults.get("language"),
        hours=str(defaults.get("hours", "")),
        address=str(defaults.get("address", "")),
        prices=str(defaults.get("prices", "")),
        services=dict(defaults.get("services", {}) or {}),
    )


@dataclass(slots=True)
class Settings:
    verify_twilio_signatures: bool
    debug_log_json: bool
    twilio_auth_token: Optional[str]
    twilio_account_sid: Optional[str]
    twilio_number: Optional[str]
    voice: str
    language: str
    fallback_voice: str
    practice: PracticeConfig

    def __post_init__(self) -> None:
        if self.verify_twilio_signatures and not self.twilio_auth_token:
            raise RuntimeError(
                "VERIFY_TWILIO_SIGNATURES is enabled but TWILIO_AUTH_TOKEN is missing."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    practice = _load_practice_config()
    env_voice = os.getenv("TTS_VOICE")
    env_lang = os.getenv("TTS_LANG")

    voice = (env_voice or practice.voice or FALLBACK_VOICE).strip()
    language = (env_lang or practice.language or FALLBACK_LANGUAGE).strip()

    return Settings(
        verify_twilio_signatures=_env_bool("VERIFY_TWILIO_SIGNATURES", False),
        debug_log_json=_env_bool("DEBUG_LOG_JSON", False),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        twilio_number=os.getenv("TWILIO_NUMBER"),
        voice=voice or FALLBACK_VOICE,
        language=language or FALLBACK_LANGUAGE,
        fallback_voice=FALLBACK_VOICE,
        practice=practice,
    )


__all__ = ["PracticeConfig", "Settings", "get_settings"]
