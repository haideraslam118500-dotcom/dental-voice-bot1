from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional


_DEF_VOICE = "Polly.Amy"
_FALLBACK_VOICE = "alice"
_LANGUAGE = "en-GB"


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
    calls_db_path: Path
    language: str = _LANGUAGE
    preferred_voice: str = _DEF_VOICE
    fallback_voice: str = _FALLBACK_VOICE

    def __post_init__(self) -> None:
        if self.verify_twilio_signatures and not self.twilio_auth_token:
            raise RuntimeError(
                "VERIFY_TWILIO_SIGNATURES is enabled but TWILIO_AUTH_TOKEN is missing."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    calls_db = Path(os.getenv("CALLS_DB_PATH", "data/calls.sqlite"))
    calls_db.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        verify_twilio_signatures=_env_bool("VERIFY_TWILIO_SIGNATURES", False),
        debug_log_json=_env_bool("DEBUG_LOG_JSON", False),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        twilio_number=os.getenv("TWILIO_NUMBER"),
        calls_db_path=calls_db,
    )


__all__ = ["Settings", "get_settings"]
