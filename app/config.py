from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from yaml import YAMLError, safe_load
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
PRACTICE_PROFILE = os.getenv("PRACTICE_PROFILE", "dental").strip().lower()
_profiled_config = ROOT / "config" / f"practice_{PRACTICE_PROFILE}.yml"
PRACTICE_CONFIG_PATH = _profiled_config if _profiled_config.exists() else ROOT / "config" / "practice.yml"
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
    service_prices: dict[str, str]
    price_items: dict[str, str]
    openings: list[str]
    backchannels: list[str]
    thinking_fillers: list[str]
    clarifiers: list[str]
    closings: list[str]
    consent_lines: dict[str, str]
    consent_snippets: list[str]
    no_speech_timeout: int
    max_silence_reprompts: int


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
        "service_prices": {
            "check-up": "A routine check-up is forty five pounds.",
            "hygiene": "Hygiene is sixty five pounds.",
            "whitening": "Whitening starts from two hundred and fifty pounds.",
            "extraction": "Tooth extraction is one hundred and twenty pounds.",
        },
        "price_items": {},
        "openings": [
            "Hi, thanks for calling Oak Dental — how can I help today?",
            "Hello, you’ve reached Oak Dental. What can I do for you?",
            "Oak Dental, good to hear from you — how can I help?",
            "Hi there, Oak Dental speaking. What do you need today?",
            "Thanks for calling Oak Dental. How can I help?",
        ],
        "backchannels": [
            "Okay, that's fine.",
            "Yeah, sure.",
            "Hmm, okay.",
            "Right, I understand.",
            "No problem.",
            "Alright.",
            "Got it.",
            "Makes sense.",
            "Absolutely.",
            "Sure thing.",
            "Okay, noted.",
            "All good.",
            "Bear with me a sec.",
            "One moment.",
            "Let me just check.",
            "No worries.",
            "That’s fine.",
        ],
        "thinking_fillers": [
            "Okay, one moment while I check.",
            "Alright, let me have a quick look.",
            "No worries, give me a second.",
            "Right, I'm checking that now.",
            "Okay, let's see what we've got.",
            "Sure, I’m pulling that up.",
        ],
        "clarifiers": [
            "Sorry, could you repeat that in a few words?",
            "I didn’t quite catch that — was that a booking, our hours, or prices?",
            "One more time please — which day did you want?",
            "Could you say that slowly for me?",
        ],
        "closings": [
            "Okay, thanks for calling. Have a lovely day. Goodbye.",
            "Alright, appreciate the call. Take care — goodbye.",
            "Thanks for calling Oak Dental. Bye for now.",
        ],
        "consent_lines": {
            "short_booking": (
                "By providing your number, you agree to receive appointment confirmations and reminders."
            )
        },
        "consent_snippets": [],
        "no_speech_timeout": 5,
        "max_silence_reprompts": 2,
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

    raw_prices = defaults.get("prices", "")
    price_items: dict[str, str]
    if isinstance(raw_prices, dict):
        price_items = {str(k): str(v) for k, v in raw_prices.items()}
        highlight_keys = ("mot", "interim_service", "full_service")
        highlights = [price_items.get(key) for key in highlight_keys if price_items.get(key)]
        price_text = " ".join(value for value in highlights if value).strip()
        if not price_text:
            price_text = " ".join(value for value in price_items.values() if value).strip()
    else:
        price_text = str(raw_prices or "")
        price_items = {str(k): str(v) for k, v in (defaults.get("price_items") or {}).items()}

    return PracticeConfig(
        practice_name=str(defaults.get("practice_name", "Oak Dental")),
        voice=defaults.get("voice"),
        language=defaults.get("language"),
        hours=str(defaults.get("hours", "")),
        address=str(defaults.get("address", "")),
        prices=price_text,
        service_prices=dict(defaults.get("service_prices", {}) or {}),
        price_items=price_items,
        openings=list(defaults.get("openings", []) or []),
        backchannels=list(defaults.get("backchannels", []) or []),
        thinking_fillers=list(defaults.get("thinking_fillers", []) or []),
        clarifiers=list(defaults.get("clarifiers", []) or []),
        closings=list(defaults.get("closings", []) or []),
        consent_lines=dict(defaults.get("consent_lines", {}) or {}),
        consent_snippets=list(defaults.get("consent_snippets", []) or []),
        no_speech_timeout=int(defaults.get("no_speech_timeout", 5) or 5),
        max_silence_reprompts=int(defaults.get("max_silence_reprompts", 2) or 2),
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
