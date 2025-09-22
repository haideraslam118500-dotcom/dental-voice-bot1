from __future__ import annotations

from typing import Optional

from twilio.twiml.voice_response import VoiceResponse


def gather_first_name(attempt: int, voice: str, language: str) -> str:
    prompt = (
        "Hello, thanks for calling the practice. What's your first name?"
        if attempt == 0
        else "Sorry, I missed that. Please tell me just your first name."
    )
    response = VoiceResponse()
    gather = response.gather(
        input="speech",
        action="/gather-intent",
        method="POST",
        speech_timeout="auto",
        language=language,
    )
    gather.say(prompt, voice=voice, language=language)
    response.pause(length=1)
    return str(response)


def gather_intent(name: str, attempt: int, voice: str, language: str) -> str:
    if attempt == 0:
        prompt = (
            f"Thanks {name}. How can I help? Say hours, address, prices, or book an appointment. "
            "Press 1 for hours, 2 for address, 3 for prices, 4 to book."
        )
    else:
        prompt = (
            "Please say hours, address, prices, or book. You can also press 1, 2, 3, or 4."
        )
    response = VoiceResponse()
    gather = response.gather(
        input="speech dtmf",
        action="/gather-intent",
        method="POST",
        num_digits=1,
        speech_timeout="auto",
        language=language,
        hints="hours,address,prices,book",
    )
    gather.say(prompt, voice=voice, language=language)
    response.pause(length=1)
    return str(response)


def gather_booking(attempt: int, voice: str, language: str) -> str:
    prompt = (
        "Great. What day and time suits you? For example, say Monday at 3 p.m."
        if attempt == 0
        else "Please say the day and time you prefer, like Tuesday 10 a.m."
    )
    response = VoiceResponse()
    gather = response.gather(
        input="speech",
        action="/gather-booking",
        method="POST",
        speech_timeout="auto",
        language=language,
    )
    gather.say(prompt, voice=voice, language=language)
    response.pause(length=1)
    return str(response)


def respond_with_information(intent: str, voice: str, language: str, name: Optional[str]) -> str:
    messages = {
        "hours": "We're open Monday to Friday from nine until five. Thanks for calling. Goodbye.",
        "address": "We're on High Street in the town centre with parking behind the surgery. Goodbye.",
        "prices": "Check-ups start at fifty pounds and whitening from two ninety. We'll send full prices on request. Goodbye.",
    }
    response = VoiceResponse()
    response.say(messages[intent], voice=voice, language=language)
    response.hangup()
    return str(response)


def respond_with_booking_confirmation(
    requested_time: str, voice: str, language: str, name: Optional[str]
) -> str:
    response = VoiceResponse()
    name_prefix = f"Thanks {name}. " if name else "Thanks. "
    response.say(
        f"{name_prefix}I'll note that you'd like {requested_time}. A team member will call back to confirm shortly. Goodbye.",
        voice=voice,
        language=language,
    )
    response.hangup()
    return str(response)


def respond_with_escalation(voice: str, language: str) -> str:
    response = VoiceResponse()
    response.say(
        "I'm sorry, I'm having trouble. I'll let the front desk know to follow up. Goodbye.",
        voice=voice,
        language=language,
    )
    response.hangup()
    return str(response)


__all__ = [
    "gather_first_name",
    "gather_intent",
    "gather_booking",
    "respond_with_information",
    "respond_with_booking_confirmation",
    "respond_with_escalation",
]
