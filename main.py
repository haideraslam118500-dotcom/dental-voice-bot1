from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from itertools import cycle
from threading import Lock
from typing import Any, Callable, Dict, Mapping, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from twilio.twiml.voice_response import VoiceResponse

from app.config import get_settings
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

OPENING_PROMPT = (
    "Hi, thanks for calling our dental practice. I’m your AI receptionist, here to help with general "
    "information and booking appointments. Please note, I’m not a medical professional. How can I help "
    "you today? You can ask about our opening hours, our address, our prices, or say you’d like to book an appointment."
)
CLARIFY_PROMPT = "Do you need our opening hours, address, prices, or would you like to book?"
ANYTHING_ELSE_PROMPT = "Is there anything else I can help with?"
BOOKING_NAME_PROMPT = "Sure, let's get you booked in. Could I take your first name?"
BOOKING_NAME_REPROMPT = "Could I just take the first name for the appointment?"
BOOKING_TIME_PROMPT_TEMPLATE = "Thanks {name}. What day and time suits you best?"
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


def _booking_time_prompt(name: Optional[str]) -> str:
    if name:
        return BOOKING_TIME_PROMPT_TEMPLATE.format(name=name)
    return "Thanks. What day and time suits you best?"


def _booking_confirmation_prompt(name: Optional[str], requested_time: Optional[str]) -> str:
    when = requested_time or "that time"
    if name:
        return f"Thanks {name}. I'll note {when}. Does that work for you?"
    return f"Thanks. I'll note {when}. Does that work for you?"


def _booking_confirmed_message(name: Optional[str], requested_time: Optional[str]) -> str:
    when = requested_time or "that time"
    if name:
        return f"Brilliant, {name}. I've noted {when} and the team will confirm shortly. {ANYTHING_ELSE_PROMPT}"
    return f"Brilliant. I've noted {when} and the team will confirm shortly. {ANYTHING_ELSE_PROMPT}"


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
    state["intent"] = "booking"
    state["caller_name"] = None
    state["requested_time"] = None
    state["stage"] = "booking_name"
    state["silence_count"] = 0
    state["retries"] = 0
    logger.info("Booking flow started", extra={"call_sid": state.get("call_sid")})
    return _respond_with_gather(state, BOOKING_NAME_PROMPT, action="/gather-booking")


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
    if intent in INFO_LINES or intent == "booking":
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input)
    if intent == "affirm" or lowered in POSITIVE_RESPONSES:
        state["stage"] = "intent"
        return _respond_with_gather(state, CLARIFY_PROMPT)
    state["stage"] = "intent"
    return _respond_with_gather(state, CLARIFY_PROMPT)


def _handle_booking_name(state: Dict[str, Any], user_input: str, intent: Optional[str]) -> Response:
    if intent == "goodbye":
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input)
    name = _extract_first_name(user_input)
    if not name:
        state["retries"] += 1
        return _respond_with_gather(state, BOOKING_NAME_REPROMPT, action="/gather-booking")
    state["caller_name"] = name
    state["stage"] = "booking_time"
    state["silence_count"] = 0
    logger.info(
        "Captured caller name",
        extra={"call_sid": state.get("call_sid"), "caller_name": name},
    )
    return _respond_with_gather(state, _booking_time_prompt(name), action="/gather-booking")


def _handle_booking_time(state: Dict[str, Any], user_input: str, intent: Optional[str]) -> Response:
    if intent == "goodbye":
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input)
    state["requested_time"] = user_input
    state["stage"] = "booking_confirm"
    state["silence_count"] = 0
    logger.info(
        "Captured requested time",
        extra={"call_sid": state.get("call_sid"), "requested_time": user_input},
    )
    return _respond_with_gather(
        state,
        _booking_confirmation_prompt(state.get("caller_name"), state.get("requested_time")),
        action="/gather-booking",
    )


def _handle_booking_confirmation(state: Dict[str, Any], user_input: str, intent: Optional[str]) -> Response:
    lowered = user_input.lower().strip()
    if intent == "goodbye" or lowered in NEGATIVE_RESPONSES:
        state["stage"] = "follow_up"
        return _respond_with_gather(state, BOOKING_DECLINED_PROMPT)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input)
    if intent == "affirm" or lowered in POSITIVE_RESPONSES:
        if not state.get("booking_logged") and state.get("requested_time"):
            append_booking(
                state.get("call_sid", ""),
                state.get("caller_name"),
                state.get("requested_time"),
            )
            state["booking_logged"] = True
            logger.info(
                "Logged booking request",
                extra={
                    "call_sid": state.get("call_sid"),
                    "caller_name": state.get("caller_name"),
                    "requested_time": state.get("requested_time"),
                },
            )
        state["stage"] = "follow_up"
        state["intent"] = "booking"
        return _respond_with_gather(
            state,
            _booking_confirmed_message(state.get("caller_name"), state.get("requested_time")),
        )
    # Treat other responses as a revised time request
    state["requested_time"] = user_input
    logger.info(
        "Clarifying booking time",
        extra={"call_sid": state.get("call_sid"), "requested_time": user_input},
    )
    return _respond_with_gather(
        state,
        _booking_confirmation_prompt(state.get("caller_name"), state.get("requested_time")),
        action="/gather-booking",
    )


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
        return _respond_with_gather(state, OPENING_PROMPT)

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
        if stage == "booking_name":
            return _handle_silence(state, reprompt=BOOKING_NAME_REPROMPT, action="/gather-booking")
        if stage == "booking_time":
            return _handle_silence(state, reprompt=BOOKING_TIME_REPROMPT, action="/gather-booking")
        if stage == "booking_confirm":
            return _handle_silence(state, reprompt=BOOKING_CONFIRM_REPROMPT, action="/gather-booking")
        return _handle_silence(state, reprompt=CLARIFY_PROMPT)

    _remember_caller_line(state, speech_result)
    state["silence_count"] = 0

    intent = parse_intent(speech_result)

    if stage == "booking_name":
        return _handle_booking_name(state, speech_result, intent)
    if stage == "booking_time":
        return _handle_booking_time(state, speech_result, intent)
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
