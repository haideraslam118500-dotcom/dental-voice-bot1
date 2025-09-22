from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv


_DEF_VOICE = "Polly.Amy"
_FALLBACK_VOICE = "alice"
_LANGUAGE = "en-GB"

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    verify_twilio_signatures: bool
    debug_log_json: bool
    twilio_auth_token: Optional[str]
    twilio_account_sid: Optional[str]
    twilio_number: Optional[str]
    language: str
    tts_voice: str
    fallback_voice: str

    def __post_init__(self) -> None:
        if self.verify_twilio_signatures and not self.twilio_auth_token:
            raise RuntimeError(
                "VERIFY_TWILIO_SIGNATURES is enabled but TWILIO_AUTH_TOKEN is missing."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        verify_twilio_signatures=_env_bool("VERIFY_TWILIO_SIGNATURES", False),
        debug_log_json=_env_bool("DEBUG_LOG_JSON", False),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        twilio_number=os.getenv("TWILIO_NUMBER"),
        language=os.getenv("TTS_LANG", _LANGUAGE),
        tts_voice=os.getenv("TTS_VOICE", _DEF_VOICE),
        fallback_voice=_FALLBACK_VOICE,
    )


__all__ = ["Settings", "get_settings"]
