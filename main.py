from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timezone
from itertools import cycle
from threading import Lock
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from twilio.twiml.voice_response import VoiceResponse

from app.config import get_settings
from app import nlp, schedule
from app.dialogue import CONFIRM_TEMPLATES, DISCLAIMER_LINE, GREETINGS
from app.intent import parse_intent
from app.logging_config import setup_logging
from app.persistence import (
    append_booking,
    append_call_record,
    ensure_storage,
    save_transcript,
    transcript_add,
    transcript_init,
    transcript_pop,
)
from app.security import TwilioRequestValidationMiddleware
from app.twilio_compat import RequestValidator

setup_logging()

logger = logging.getLogger(__name__)

settings = get_settings()
ensure_storage()

VOICE = settings.voice
LANGUAGE = settings.language

_voice_lock = Lock()
_active_voice = VOICE
_voice_fallback_notified = False

MENU_STATEMENT = "I can help with our hours, address, prices, or book you in."
CLARIFY_PROMPT = "Would you like our hours, address, prices, or to book an appointment?"
ANYTHING_ELSE_PROMPT = "Is there anything else I can help with?"
BOOKING_TIME_PROMPT = "Sure, let's find you a time. What day and time works for you?"
BOOKING_NAME_PROMPT = "What's the name for the appointment?"
BOOKING_NAME_REPROMPT = "Could I take the name for the appointment?"
BOOKING_TIME_PROMPT_TEMPLATE = "Thanks {name}. What day and time works for you?"
BOOKING_TIME_REPROMPT = "What day and time would you like to come in?"
BOOKING_CONFIRM_REPROMPT = "Should I pencil that appointment in for you?"
BOOKING_DECLINED_PROMPT = "No problem, we won't lock anything in just yet. Is there anything else I can help with?"

INFO_LINES = {
    "hours": settings.practice.hours,
    "address": settings.practice.address,
    "prices": settings.practice.prices,
}

GOODBYES = [
    "Okay, have a lovely day. Goodbye.",
    "Thanks for calling, take care. Goodbye.",
    "Alright then, wishing you a wonderful day. Goodbye.",
    "Thanks again for calling. Speak soon. Goodbye.",
    "Take care and enjoy the rest of your day. Goodbye.",
]
_goodbye_cycle = cycle(GOODBYES)

NEGATIVE_RESPONSES = {
    "no",
    "no thanks",
    "no thank you",
    "nothing else",
    "that's all",
    "that is all",
    "we're good",
    "were good",
    "nah",
    "nope",
}
POSITIVE_RESPONSES = {
    "yes",
    "yeah",
    "yep",
    "sure",
    "ok",
    "okay",
    "alright",
    "please",
    "sounds good",
}


def _get_active_voice() -> str:
    with _voice_lock:
        return _active_voice


def _set_active_voice(voice: str) -> None:
    global _active_voice
    with _voice_lock:
        _active_voice = voice


def _say_with_voice(
    say_callable: Callable[[str, Optional[str], Optional[str]], Any],
    message: str,
    *,
    preferred_voice: str,
    language: str,
    call_sid: Optional[str] = None,
) -> None:
    try:
        say_callable(message, voice=preferred_voice, language=language)
    except Exception:  # pragma: no cover - depends on Twilio SDK behaviour
        fallback_voice = settings.fallback_voice or "alice"
        if fallback_voice == preferred_voice:
            raise
        _set_active_voice(fallback_voice)
        global _voice_fallback_notified
        if not _voice_fallback_notified:
            logger.warning(
                "Preferred voice unavailable; falling back",
                extra={
                    "call_sid": call_sid,
                    "preferred_voice": preferred_voice,
                    "fallback_voice": fallback_voice,
                },
                exc_info=True,
            )
            _voice_fallback_notified = True
        say_callable(message, voice=fallback_voice, language=language)


_state_lock = Lock()
_call_states: Dict[str, Dict[str, Any]] = {}
CALLS = _call_states

app = FastAPI()

from app.debug import router as debug_router

app.include_router(debug_router)

validator = RequestValidator(settings.twilio_auth_token) if settings.twilio_auth_token else None
protected_paths = ("/voice", "/gather-intent", "/gather-booking", "/status")
app.add_middleware(
    TwilioRequestValidationMiddleware,
    validator=validator,
    enabled=settings.verify_twilio_signatures,
    protected_paths=protected_paths,
)


def _initial_state(call_sid: str, form_data: Mapping[str, Any]) -> Dict[str, Any]:
    metadata = {
        "from": form_data.get("From"),
        "to": form_data.get("To"),
        "direction": form_data.get("Direction"),
        "account_sid": form_data.get("AccountSid"),
    }
    transcript_lines = transcript_init(call_sid)
    return {
        "call_sid": call_sid,
        "transcript": transcript_lines,
        "retries": 0,
        "intent": None,
        "caller_name": None,
        "requested_time": None,
        "started_at": datetime.now(tz=timezone.utc),
        "transcript_file": None,
        "stage": "intent",
        "silence_count": 0,
        "greeted": False,
        "booking_logged": False,
        "metadata": metadata,
    }


def _get_state(
    call_sid: str,
    form_data: Optional[Mapping[str, Any]] = None,
    *,
    create: bool = True,
) -> Optional[Dict[str, Any]]:
    with _state_lock:
        state = _call_states.get(call_sid)
        if state is None and create:
            state = _initial_state(call_sid, dict(form_data or {}))
            _call_states[call_sid] = state
        if state is not None and form_data:
            metadata = state.setdefault("metadata", {})
            for key, form_key in (
                ("from", "From"),
                ("to", "To"),
                ("direction", "Direction"),
                ("account_sid", "AccountSid"),
            ):
                value = form_data.get(form_key)
                if value:
                    metadata[key] = value
            duration = form_data.get("CallDuration")
            if duration:
                metadata["duration_sec"] = duration
        return state


def _pop_state(call_sid: str) -> Optional[Dict[str, Any]]:
    with _state_lock:
        return _call_states.pop(call_sid, None)


def _next_goodbye() -> str:
    return next(_goodbye_cycle)


def _twiml_response(twiml: str) -> Response:
    return Response(content=twiml, media_type="application/xml")


def _build_opening_prompt() -> str:
    greeting = random.choice(GREETINGS)
    parts = [greeting]
    if DISCLAIMER_LINE:
        parts.append(DISCLAIMER_LINE)
    lower = greeting.lower()
    if not any(keyword in lower for keyword in ("hours", "prices", "booking")):
        parts.append(MENU_STATEMENT)
        parts.append(CLARIFY_PROMPT)
    return " ".join(part for part in parts if part)


def create_gather_twiml(
    prompt: str,
    *,
    action: str,
    voice: str,
    language: str,
    hints: Optional[str] = None,
    timeout: int = 5,
    call_sid: Optional[str] = None,
) -> str:
    response = VoiceResponse()
    gather_kwargs = {
        "input": "speech",
        "action": action,
        "method": "POST",
        "timeout": timeout,
        "speech_timeout": "auto",
        "barge_in": True,
        "language": language,
    }
    if hints:
        gather_kwargs["hints"] = hints
    gather = response.gather(**gather_kwargs)
    _say_with_voice(
        gather.say,
        prompt,
        preferred_voice=voice,
        language=language,
        call_sid=call_sid,
    )
    return str(response)


def create_goodbye_twiml(
    message: str,
    *,
    voice: str,
    language: str,
    call_sid: Optional[str] = None,
) -> str:
    response = VoiceResponse()
    _say_with_voice(
        response.say,
        message,
        preferred_voice=voice,
        language=language,
        call_sid=call_sid,
    )
    response.hangup()
    return str(response)


def _remember_agent_line(state: Dict[str, Any], text: str) -> None:
    text = (text or "").strip()
    if text:
        call_sid = (state.get("call_sid") or "").strip()
        if call_sid:
            transcript_add(call_sid, "Agent", text)


def _remember_caller_line(state: Dict[str, Any], text: str) -> None:
    text = (text or "").strip()
    if text:
        call_sid = (state.get("call_sid") or "").strip()
        if call_sid:
            transcript_add(call_sid, "Caller", text)


def _respond_with_gather(
    state: Dict[str, Any],
    prompt: str,
    *,
    action: str = "/gather-intent",
    hints: Optional[str] = None,
) -> Response:
    _remember_agent_line(state, prompt)
    twiml = create_gather_twiml(
        prompt,
        action=action,
        voice=_get_active_voice(),
        language=LANGUAGE,
        hints=hints,
        call_sid=state.get("call_sid"),
    )
    return _twiml_response(twiml)


def _respond_with_goodbye(state: Dict[str, Any]) -> Response:
    message = _next_goodbye()
    _remember_agent_line(state, message)
    state["stage"] = "completed"
    logger.info("Ending call", extra={"call_sid": state.get("call_sid"), "message": message})
    return _twiml_response(
        create_goodbye_twiml(
            message,
            voice=_get_active_voice(),
            language=LANGUAGE,
            call_sid=state.get("call_sid"),
        )
    )


def _booking_type_prompt() -> str:
    return "Sure, what type of appointment would you like? For example check-up, hygiene, or whitening?"


def _booking_type_reprompt() -> str:
    return "We can do check-up, hygiene, whitening, filling, or emergency. Which would you like?"


def _booking_date_prompt(appt_type: str) -> str:
    return f"Great, a {appt_type} — what day works best for you?"


def _booking_date_reprompt() -> str:
    return "Which day works best for you? You can say tomorrow or a weekday like Wednesday."


def _format_times(slots: Sequence[str]) -> str:
    if not slots:
        return ""
    if len(slots) == 1:
        return slots[0]
    if len(slots) == 2:
        return " or ".join(slots)
    return ", ".join(slots[:-1]) + f", or {slots[-1]}"


def _booking_time_prompt(date: str, slots: Sequence[str]) -> str:
    joined = _format_times(list(slots))
    if not joined:
        return "I couldn't see any free times on that day. Would another day work?"
    return f"On {date}, we have {joined}. Which time works for you?"


def _booking_time_reprompt(slots: Sequence[str]) -> str:
    cleaned = [slot for slot in slots if slot]
    if cleaned:
        preview = ", ".join(cleaned[:3])
        return f"Times available are {preview}. Which would you like?"
    return "What time suits you? You can say ten a m, ten thirty, or three p m."


def _booking_name_prompt(time: str) -> str:
    return f"Okay, {time} noted. And your name please?"


def _booking_confirm_prompt(state: Dict[str, Any]) -> str:
    return (
        f"Great, {state['caller_name']}. Shall I book you in for {state['booking_appt_type']} "
        f"on {state['booking_date']} at {state['booking_time']}?"
    )


def _booking_confirmed_message(state: Dict[str, Any]) -> str:
    msg = random.choice(CONFIRM_TEMPLATES).format(
        date=state["booking_date"],
        time=state["booking_time"],
        type=state["booking_appt_type"],
        name=state["caller_name"] or "",
    )
    return f"{msg} Anything else I can help with?"


def _reset_booking_context(state: Dict[str, Any]) -> None:
    state["intent"] = "booking"
    state["booking_appt_type"] = None
    state["booking_date"] = None
    state["booking_time"] = None
    state["booking_available_times"] = []
    state["requested_time"] = None
    state["caller_name"] = None
    state["booking_logged"] = False
    state["booking_suggested_slot"] = None


def _available_slots_for_date(date: str, limit: int = 6) -> list[str]:
    slots = schedule.list_available(date=date, limit=limit)
    return [slot["start_time"] for slot in slots]


def _next_available_slot() -> Optional[dict]:
    return schedule.find_next_available()


def _match_appointment_type(text: str) -> Optional[str]:
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return None
    for appt in schedule.APPT_TYPES:
        if cleaned == appt.lower():
            return appt
    for appt in schedule.APPT_TYPES:
        if cleaned in appt.lower():
            return appt
    return None


def _handle_availability_request(state: Dict[str, Any], user_input: str) -> Response:
    date = nlp.parse_date_phrase(user_input)
    if not date:
        state["stage"] = "booking_date"
        state["silence_count"] = 0
        state["retries"] = 0
        state["booking_date"] = None
        state["booking_available_times"] = []
        return _respond_with_gather(
            state,
            "Sure — which day are you thinking of? You can say tomorrow or a weekday like Wednesday.",
            action="/gather-booking",
        )

    slots = _available_slots_for_date(date)
    if not slots:
        nxt = _next_available_slot()
        if nxt:
            message = (
                f"That day looks full. The next available is {nxt['date']} at {nxt['start_time']}. Would you like that?"
            )
        else:
            message = "Sorry, I can’t see any free times right now."
        state["booking_date"] = date
        state["booking_available_times"] = []
        state["stage"] = "booking_date"
        state["silence_count"] = 0
        state["retries"] = 0
        return _respond_with_gather(state, message, action="/gather-booking")

    state.setdefault("intent", "booking")
    state["booking_date"] = date
    state["booking_available_times"] = slots
    state["stage"] = "booking_time"
    state["silence_count"] = 0
    state["retries"] = 0
    prompt = _booking_time_prompt(date, slots)
    return _respond_with_gather(state, prompt, action="/gather-booking")


def _extract_first_name(text: str) -> Optional[str]:
    cleaned = text.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    for prefix in ("my name is", "it's", "its", "this is", "i am", "i'm", "call me"):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    parts = [piece for piece in re.split(r"[^a-zA-Z]+", cleaned) if piece]
    if not parts:
        return None
    return parts[0].capitalize()


def _safe_int(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _handle_silence(
    state: Dict[str, Any],
    *,
    reprompt: str,
    action: str = "/gather-intent",
) -> Response:
    state["silence_count"] = state.get("silence_count", 0) + 1
    state["retries"] = state.get("retries", 0) + 1
    logger.info(
        "Silence detected",
        extra={"call_sid": state.get("call_sid"), "count": state["silence_count"], "stage": state.get("stage")},
    )
    if state["silence_count"] == 1:
        return _respond_with_gather(state, reprompt, action=action)
    if state["silence_count"] == 2:
        state["stage"] = "follow_up"
        return _respond_with_gather(state, ANYTHING_ELSE_PROMPT)
    return _respond_with_goodbye(state)


def _start_booking(state: Dict[str, Any]) -> Response:
    _reset_booking_context(state)
    state["stage"] = "booking_type"
    state["silence_count"] = 0
    state["retries"] = 0
    logger.info("Booking flow started", extra={"call_sid": state.get("call_sid")})
    return _respond_with_gather(state, _booking_type_prompt(), action="/gather-booking")


def _handle_primary_intent(state: Dict[str, Any], intent: Optional[str], user_input: str) -> Response:
    lowered = user_input.lower().strip()
    if intent == "goodbye" or lowered in NEGATIVE_RESPONSES:
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        message = f"{INFO_LINES[intent]} {ANYTHING_ELSE_PROMPT}"
        state["intent"] = intent
        state["stage"] = "follow_up"
        state["retries"] = 0
        logger.info("Providing information", extra={"call_sid": state.get("call_sid"), "intent": intent})
        return _respond_with_gather(state, message)
    if intent == "availability":
        if state.get("intent") != "booking":
            _reset_booking_context(state)
        return _handle_availability_request(state, user_input)
    if intent == "booking":
        return _start_booking(state)
    if intent == "affirm" or lowered in POSITIVE_RESPONSES:
        state["stage"] = "intent"
        return _respond_with_gather(state, CLARIFY_PROMPT)
    state["intent"] = state.get("intent") or "other"
    return _respond_with_gather(state, CLARIFY_PROMPT)


def _handle_follow_up(state: Dict[str, Any], intent: Optional[str], user_input: str) -> Response:
    lowered = user_input.lower().strip()
    if intent == "goodbye" or lowered in NEGATIVE_RESPONSES:
        return _respond_with_goodbye(state)
    if intent == "availability":
        if state.get("intent") != "booking":
            _reset_booking_context(state)
        return _handle_availability_request(state, user_input)
    if intent in INFO_LINES or intent == "booking":
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input)
    if intent == "affirm" or lowered in POSITIVE_RESPONSES:
        state["stage"] = "intent"
        return _respond_with_gather(state, CLARIFY_PROMPT)
    state["stage"] = "intent"
    return _respond_with_gather(state, CLARIFY_PROMPT)


def _handle_booking_type(state: Dict[str, Any], user_input: str, intent: Optional[str]) -> Response:
    if intent == "goodbye":
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input)
    if intent == "availability":
        return _handle_availability_request(state, user_input)

    match = _match_appointment_type(user_input)
    if not match:
        state["retries"] += 1
        return _respond_with_gather(state, _booking_type_reprompt(), action="/gather-booking")

    state["booking_appt_type"] = match
    state["silence_count"] = 0
    state["retries"] = 0
    logger.info(
        "Captured appointment type",
        extra={"call_sid": state.get("call_sid"), "appointment_type": match},
    )
    if state.get("booking_date") and state.get("booking_time"):
        state["stage"] = "booking_name"
        return _respond_with_gather(state, _booking_name_prompt(state["booking_time"]), action="/gather-booking")
    state["stage"] = "booking_date"
    return _respond_with_gather(state, _booking_date_prompt(match), action="/gather-booking")


def _handle_booking_date(state: Dict[str, Any], user_input: str, intent: Optional[str]) -> Response:
    lowered = user_input.lower().strip()
    if intent == "goodbye" or lowered in NEGATIVE_RESPONSES:
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input)
    if intent == "availability":
        return _handle_availability_request(state, user_input)

    suggested = state.get("booking_suggested_slot")
    if suggested and (intent == "affirm" or lowered in POSITIVE_RESPONSES):
        state["booking_date"] = suggested["date"]
        state["booking_time"] = suggested["start_time"]
        state["booking_available_times"] = [suggested["start_time"]]
        state["requested_time"] = f"{suggested['date']} {suggested['start_time']}"
        state["booking_suggested_slot"] = None
        state["stage"] = "booking_name"
        state["silence_count"] = 0
        return _respond_with_gather(state, _booking_name_prompt(suggested["start_time"]), action="/gather-booking")

    parsed = nlp.parse_date_phrase(user_input)
    if not parsed:
        state["retries"] += 1
        return _respond_with_gather(state, _booking_date_reprompt(), action="/gather-booking")

    state["booking_date"] = parsed
    slots = _available_slots_for_date(parsed)
    state["booking_available_times"] = slots
    state["booking_suggested_slot"] = None
    state["silence_count"] = 0
    state["retries"] = 0
    if not slots:
        nxt = _next_available_slot()
        if nxt:
            state["booking_suggested_slot"] = nxt
            message = (
                f"Sorry, no free times on that day. The next available is {nxt['date']} at {nxt['start_time']}. Would you like that?"
            )
        else:
            message = "Sorry, I can’t see any available times in the schedule right now."
        return _respond_with_gather(state, message, action="/gather-booking")

    state["stage"] = "booking_time"
    prompt = _booking_time_prompt(parsed, slots)
    return _respond_with_gather(state, prompt, action="/gather-booking")


def _handle_booking_time(state: Dict[str, Any], user_input: str, intent: Optional[str]) -> Response:
    if intent == "goodbye":
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input)
    if intent == "availability":
        return _handle_availability_request(state, user_input)

    hhmm = nlp.normalize_time(user_input)
    if not hhmm:
        state["retries"] += 1
        return _respond_with_gather(
            state,
            _booking_time_reprompt(state.get("booking_available_times", [])),
            action="/gather-booking",
        )

    avail = set(state.get("booking_available_times") or [])
    if state.get("booking_date") and not avail:
        avail = set(_available_slots_for_date(state["booking_date"]))
        state["booking_available_times"] = list(avail)
    if avail and hhmm not in avail:
        state["retries"] += 1
        return _respond_with_gather(
            state,
            _booking_time_reprompt(list(avail)),
            action="/gather-booking",
        )

    state["booking_time"] = hhmm
    if state.get("booking_date"):
        state["requested_time"] = f"{state['booking_date']} {hhmm}"
    else:
        state["requested_time"] = hhmm
    state["silence_count"] = 0
    state["retries"] = 0
    logger.info(
        "Captured booking time",
        extra={"call_sid": state.get("call_sid"), "time": hhmm, "date": state.get("booking_date")},
    )

    if state.get("booking_appt_type"):
        state["stage"] = "booking_name"
        return _respond_with_gather(state, _booking_name_prompt(hhmm), action="/gather-booking")

    state["stage"] = "booking_type"
    return _respond_with_gather(state, _booking_type_prompt(), action="/gather-booking")


def _handle_booking_name(state: Dict[str, Any], user_input: str, intent: Optional[str]) -> Response:
    if intent == "goodbye":
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input)
    if intent == "availability":
        return _handle_availability_request(state, user_input)

    name = _extract_first_name(user_input)
    if not name:
        state["retries"] += 1
        return _respond_with_gather(state, BOOKING_NAME_REPROMPT, action="/gather-booking")

    state["caller_name"] = name
    state["stage"] = "booking_confirm"
    state["silence_count"] = 0
    state["retries"] = 0
    logger.info(
        "Captured caller name",
        extra={"call_sid": state.get("call_sid"), "caller_name": name},
    )
    return _respond_with_gather(state, _booking_confirm_prompt(state), action="/gather-booking")


def _handle_booking_confirmation(state: Dict[str, Any], user_input: str, intent: Optional[str]) -> Response:
    lowered = user_input.lower().strip()
    if intent == "goodbye" or lowered in NEGATIVE_RESPONSES:
        state["stage"] = "follow_up"
        return _respond_with_gather(state, BOOKING_DECLINED_PROMPT)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input)
    if intent == "availability":
        return _handle_availability_request(state, user_input)

    if intent == "affirm" or lowered in POSITIVE_RESPONSES:
        date = state.get("booking_date")
        time = state.get("booking_time")
        name = state.get("caller_name") or ""
        appt_type = state.get("booking_appt_type") or ""
        if not (date and time and name and appt_type):
            state["stage"] = "booking_type"
            return _respond_with_gather(state, _booking_type_prompt(), action="/gather-booking")
        ok = schedule.reserve_slot(date, time, name, appt_type)
        if ok:
            state["requested_time"] = f"{date} {time}"
            state["booking_logged"] = True
            state["stage"] = "follow_up"
            state["intent"] = "booking"
            return _respond_with_gather(state, _booking_confirmed_message(state))
        state["stage"] = "booking_date"
        state["booking_time"] = None
        state["booking_available_times"] = _available_slots_for_date(date) if date else []
        return _respond_with_gather(
            state,
            "Sorry, that slot was just taken. Would you like to pick another time?",
            action="/gather-booking",
        )

    state["retries"] += 1
    return _respond_with_gather(state, _booking_confirm_prompt(state), action="/gather-booking")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True})


def _missing_call_sid_response() -> Response:
    fallback = "Thanks for calling. Goodbye."
    return _twiml_response(
        create_goodbye_twiml(
            fallback,
            voice=_get_active_voice(),
            language=LANGUAGE,
        )
    )


@app.post("/voice")
async def voice_webhook(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    if not call_sid:
        logger.warning("CallSid missing on /voice request")
        return _missing_call_sid_response()

    state = _get_state(call_sid, form)
    assert state is not None

    speech_result = (form.get("SpeechResult") or "").strip()
    if speech_result:
        transcript_add(call_sid, "Caller", speech_result)

    if not state.get("greeted"):
        state["greeted"] = True
        state["stage"] = "intent"
        state["silence_count"] = 0
        state["retries"] = 0
        logger.info("Incoming call", extra={"call_sid": call_sid})
        return _respond_with_gather(state, _build_opening_prompt())

    return _respond_with_gather(state, CLARIFY_PROMPT)


@app.post("/gather-intent")
async def gather_intent_route(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    if not call_sid:
        logger.warning("CallSid missing on /gather-intent request")
        return _missing_call_sid_response()

    state = _get_state(call_sid, form)
    assert state is not None

    speech_result = (form.get("SpeechResult") or "").strip()
    if not speech_result:
        reprompt = CLARIFY_PROMPT if state.get("stage") == "intent" else ANYTHING_ELSE_PROMPT
        return _handle_silence(state, reprompt=reprompt)

    _remember_caller_line(state, speech_result)
    state["silence_count"] = 0

    intent = parse_intent(speech_result)
    logger.info(
        "Parsed caller input",
        extra={"call_sid": call_sid, "intent": intent, "stage": state.get("stage")},
    )

    if state.get("stage") == "follow_up":
        return _handle_follow_up(state, intent, speech_result)
    state["stage"] = "intent"
    return _handle_primary_intent(state, intent, speech_result)


@app.post("/gather-booking")
async def gather_booking_route(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    if not call_sid:
        logger.warning("CallSid missing on /gather-booking request")
        return _missing_call_sid_response()

    state = _get_state(call_sid, form)
    assert state is not None

    speech_result = (form.get("SpeechResult") or "").strip()
    stage = state.get("stage")
    if not speech_result:
        if stage == "booking_type":
            return _handle_silence(
                state,
                reprompt=_booking_type_reprompt(),
                action="/gather-booking",
            )
        if stage == "booking_date":
            return _handle_silence(
                state,
                reprompt=_booking_date_reprompt(),
                action="/gather-booking",
            )
        if stage == "booking_name":
            return _handle_silence(state, reprompt=BOOKING_NAME_REPROMPT, action="/gather-booking")
        if stage == "booking_time":
            return _handle_silence(
                state,
                reprompt=_booking_time_reprompt(state.get("booking_available_times", [])),
                action="/gather-booking",
            )
        if stage == "booking_confirm":
            return _handle_silence(state, reprompt=BOOKING_CONFIRM_REPROMPT, action="/gather-booking")
        return _handle_silence(state, reprompt=CLARIFY_PROMPT)

    _remember_caller_line(state, speech_result)
    state["silence_count"] = 0

    intent = parse_intent(speech_result)

    if stage == "booking_type":
        return _handle_booking_type(state, speech_result, intent)
    if stage == "booking_date":
        return _handle_booking_date(state, speech_result, intent)
    if stage == "booking_time":
        return _handle_booking_time(state, speech_result, intent)
    if stage == "booking_name":
        return _handle_booking_name(state, speech_result, intent)
    if stage == "booking_confirm":
        return _handle_booking_confirmation(state, speech_result, intent)

    return _handle_primary_intent(state, intent, speech_result)


@app.post("/status")
async def status_callback(request: Request) -> JSONResponse:
    form = await request.form()
    call_sid = form.get("CallSid")
    call_status = (form.get("CallStatus") or "").lower()

    logger.info("Status callback", extra={"call_sid": call_sid, "status": call_status})

    if not call_sid:
        return JSONResponse({"ok": True})

    state = _get_state(call_sid, form, create=False)

    if call_status == "completed":
        state = state or _initial_state(call_sid, dict(form))
        transcript_lines = transcript_pop(call_sid)
        if transcript_lines:
            transcript_lines = list(transcript_lines)
        else:
            transcript_lines = list(state.get("transcript") or [])
        transcript_path = save_transcript(call_sid, transcript_lines)
        state["transcript"] = transcript_lines
        state["transcript_file"] = str(transcript_path)

        if state.get("intent") == "booking" and state.get("requested_time") and not state.get("booking_logged"):
            append_booking(call_sid, state.get("caller_name"), state.get("requested_time"))
            state["booking_logged"] = True

        metadata = state.get("metadata", {})
        summary = {
            "call_sid": call_sid,
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
            "direction": form.get("Direction") or metadata.get("direction"),
            "from": form.get("From") or metadata.get("from"),
            "to": form.get("To") or metadata.get("to"),
            "duration_sec": _safe_int(form.get("CallDuration") or metadata.get("duration_sec")),
            "caller_name": state.get("caller_name"),
            "intent": state.get("intent") or "other",
            "requested_time": state.get("requested_time"),
            "transcript_file": str(transcript_path),
        }
        append_call_record(summary)
        _pop_state(call_sid)
        logger.info(
            "Call completed",
            extra={"call_sid": call_sid, "transcript_file": str(transcript_path)},
        )

    return JSONResponse({"ok": True})


__all__ = ["app", "create_gather_twiml", "create_goodbye_twiml"]
