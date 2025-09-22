from __future__ import annotations

from typing import Optional

from app.twilio_compat import VoiceResponse


def _gather(
    prompt: str,
    voice: str,
    language: str,
    *,
    action: str,
    allow_digits: bool,
    num_digits: Optional[int] = None,
    hints: Optional[str] = None,
) -> str:
    response = VoiceResponse()
    gather_kwargs = {
        "input": "speech dtmf" if allow_digits else "speech",
        "action": action,
        "method": "POST",
        "speech_timeout": "auto",
        "timeout": 3,
        "barge_in": True,
        "language": language,
    }
    if allow_digits and num_digits:
        gather_kwargs["num_digits"] = num_digits
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
        allow_digits=False,
        hints="hours,address,prices,book",
    )


def gather_for_follow_up(prompt: str, voice: str, language: str) -> str:
    return _gather(
        prompt,
        voice,
        language,
        action="/gather-intent",
        allow_digits=False,
        hints="yes,no,bye",
    )


def gather_for_name(prompt: str, voice: str, language: str) -> str:
    return _gather(
        prompt,
        voice,
        language,
        action="/gather-booking",
        allow_digits=False,
    )


def gather_for_time(prompt: str, voice: str, language: str) -> str:
    return _gather(
        prompt,
        voice,
        language,
        action="/gather-booking",
        allow_digits=True,
    )


def respond_with_goodbye(message: str, voice: str, language: str) -> str:
    response = VoiceResponse()
    response.say(message, voice=voice, language=language)
    response.hangup()
    return str(response)


__all__ = [
    "gather_for_intent",
    "gather_for_follow_up",
    "gather_for_name",
    "gather_for_time",
    "respond_with_goodbye",
]
