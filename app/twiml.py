from __future__ import annotations

from typing import Optional

from app.twilio_compat import VoiceResponse


def say_ssml(ssml: str) -> str:
    """Return a TwiML <Say> block containing raw SSML content."""
    from app.config import get_settings

    settings = get_settings()
    voice = settings.practice.voice or settings.voice or "Polly.Brian"
    language = settings.practice.language or settings.language or "en-GB"
    return f'<Say voice="{voice}" language="{language}">{ssml}</Say>'


def _gather(
    prompt: str,
    voice: str,
    language: str,
    *,
    action: str,
    hints: Optional[str] = None,
) -> str:
    response = VoiceResponse()
    gather_kwargs = {
        "input": "speech",
        "action": action,
        "method": "POST",
        "speech_timeout": "auto",
        "timeout": 3,
        "barge_in": True,
        "language": language,
    }
    if hints:
        gather_kwargs["hints"] = hints
    gather = response.gather(**gather_kwargs)
    gather.say(prompt, voice=voice, language=language)
    return str(response)


def gather_for_intent(prompt: str, voice: str, language: str) -> str:
    return _gather(
        prompt,
        voice,
        language,
        action="/gather-intent",
        hints="hours,address,prices,book",
    )


def gather_for_follow_up(prompt: str, voice: str, language: str) -> str:
    return _gather(
        prompt,
        voice,
        language,
        action="/gather-intent",
        hints="yes,no,bye",
    )


def gather_for_name(prompt: str, voice: str, language: str) -> str:
    return _gather(
        prompt,
        voice,
        language,
        action="/gather-booking",
    )


def gather_for_time(prompt: str, voice: str, language: str) -> str:
    return _gather(
        prompt,
        voice,
        language,
        action="/gather-booking",
    )


def respond_with_goodbye(message: str, voice: str, language: str) -> str:
    response = VoiceResponse()
    response.say(message, voice=voice, language=language)
    response.hangup()
    return str(response)


__all__ = [
    "say_ssml",
    "gather_for_intent",
    "gather_for_follow_up",
    "gather_for_name",
    "gather_for_time",
    "respond_with_goodbye",
]
