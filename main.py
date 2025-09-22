from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Set

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from app import dialogue
from app.config import get_settings
from app.intent import parse_intent
from app.logging_config import setup_logging
from app.persistence import append_booking, append_call_record, ensure_storage, save_transcript
from app.security import TwilioRequestValidationMiddleware
from app.state import CallState, CallStateStore
from app.twilio_compat import RequestValidator
from app.twiml import (
    gather_for_follow_up,
    gather_for_intent,
    gather_for_name,
    gather_for_time,
    respond_with_goodbye,
)

logger = logging.getLogger(__name__)

settings = get_settings()
setup_logging(settings.debug_log_json)
ensure_storage()

voice = settings.tts_voice or settings.fallback_voice
language = settings.language

state_store = CallStateStore()
completed_calls: Set[str] = set()

validator = RequestValidator(settings.twilio_auth_token) if settings.twilio_auth_token else None

protected_paths = ("/voice", "/gather-intent", "/gather-booking", "/status")
app = FastAPI()
app.add_middleware(
    TwilioRequestValidationMiddleware,
    validator=validator,
    enabled=settings.verify_twilio_signatures,
    protected_paths=protected_paths,
)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _twiml_response(twiml: str) -> Response:
    return Response(content=twiml, media_type="application/xml")


def _initial_prompt() -> str:
    return dialogue.build_menu_prompt()


def _initial_reprompt() -> str:
    return dialogue.compose_initial_reprompt()


def _continuation_prompt() -> str:
    holder = dialogue.pick_holder()
    return (
        f"{holder} What else can I help with? You can ask about our opening hours, our address, our prices, "
        "or let me know if you'd like to book an appointment."
    )


def _intent_clarifier_prompt() -> str:
    clarifier = dialogue.pick_clarifier()
    return (
        f"{clarifier} You can ask about our opening hours, our address, our prices, or say you'd like to "
        "book an appointment."
    )


def _name_clarifier_prompt() -> str:
    return dialogue.pick_name_clarifier()


def _time_clarifier_prompt() -> str:
    return dialogue.pick_time_clarifier()


def _anything_else_prompt() -> str:
    return dialogue.compose_anything_else_prompt()


def _extract_name(text: str) -> Optional[str]:
    cleaned = text.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    for prefix in ("my name is", "it's", "its", "this is", "i am", "i'm"):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    parts = cleaned.replace(",", " ").split()
    if not parts:
        return None
    name = parts[0]
    if not name:
        return None
    return name.capitalize()


def _reset_state(state: CallState, form_data) -> None:
    state.caller_name = None
    state.intent = None
    state.requested_time = None
    state.transcript.clear()
    state.awaiting = "intent"
    state.retries = {"intent": 0, "name": 0, "time": 0}
    state.silence_count = 0
    state.completed = False
    state.transcript_file = None
    state.final_goodbye = None
    state.has_greeted = False
    state.prompted_after_greeting = False
    state.metadata = {
        "from": form_data.get("From"),
        "to": form_data.get("To"),
        "direction": form_data.get("Direction"),
        "account_sid": form_data.get("AccountSid"),
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def _goodbye(state: CallState) -> Response:
    message = dialogue.pick_goodbye()
    state.final_goodbye = message
    state.completed = True
    state.add_system_line(message)
    logger.info("Ending call", extra={"call_sid": state.call_sid, "goodbye": message})
    return _twiml_response(respond_with_goodbye(message, voice, language))


def _handle_silence(state: CallState, stage: str) -> Response:
    state.silence_count += 1
    logger.info(
        "Silence detected",
        extra={"call_sid": state.call_sid, "stage": stage, "count": state.silence_count},
    )
    if state.awaiting == "anything_else":
        return _goodbye(state)
    if state.silence_count >= 2:
        state.awaiting = "anything_else"
        prompt = _anything_else_prompt()
        state.add_system_line(prompt)
        return _twiml_response(gather_for_follow_up(prompt, voice, language))
    if stage == "name":
        prompt = _name_clarifier_prompt()
        state.add_system_line(prompt)
        return _twiml_response(gather_for_name(prompt, voice, language))
    if stage == "time":
        prompt = _time_clarifier_prompt()
        state.add_system_line(prompt)
        return _twiml_response(gather_for_time(prompt, voice, language))
    prompt = _intent_clarifier_prompt()
    state.add_system_line(prompt)
    return _twiml_response(gather_for_intent(prompt, voice, language))


def _respond_with_info(state: CallState, intent: str) -> Response:
    state.intent = intent
    state.awaiting = "anything_else"
    state.reset_retries("intent")
    prompt = dialogue.compose_info_prompt(intent)
    state.add_system_line(prompt)
    logger.info("Providing information", extra={"call_sid": state.call_sid, "intent": intent})
    return _twiml_response(gather_for_follow_up(prompt, voice, language))


def _start_booking(state: CallState) -> Response:
    state.intent = "booking"
    state.awaiting = "name"
    state.reset_retries("intent")
    state.reset_retries("name")
    prompt = dialogue.compose_booking_name_prompt()
    state.add_system_line(prompt)
    logger.info("Booking flow started", extra={"call_sid": state.call_sid})
    return _twiml_response(gather_for_name(prompt, voice, language))


def _ask_for_time(state: CallState) -> Response:
    prompt = dialogue.compose_booking_time_prompt(state.caller_name)
    state.add_system_line(prompt)
    state.awaiting = "time"
    state.reset_retries("time")
    logger.info(
        "Captured caller name",
        extra={"call_sid": state.call_sid, "caller_name": state.caller_name},
    )
    return _twiml_response(gather_for_time(prompt, voice, language))


def _confirm_booking(state: CallState) -> Response:
    prompt = dialogue.compose_booking_confirmation(state.caller_name, state.requested_time or "")
    state.add_system_line(prompt)
    state.awaiting = "anything_else"
    logger.info(
        "Captured booking request",
        extra={
            "call_sid": state.call_sid,
            "caller_name": state.caller_name,
            "requested_time": state.requested_time,
        },
    )
    return _twiml_response(gather_for_follow_up(prompt, voice, language))


def _handle_intent(state: CallState, intent: Optional[str], user_input: str) -> Response:
    if state.awaiting == "anything_else":
        return _handle_anything_else(state, intent, user_input)

    if intent == "goodbye":
        return _goodbye(state)
    if intent == "affirm":
        prompt = _continuation_prompt()
        state.add_system_line(prompt)
        return _twiml_response(gather_for_intent(prompt, voice, language))
    if intent in {"hours", "address", "prices"}:
        return _respond_with_info(state, intent)
    if intent == "booking":
        return _start_booking(state)
    state.bump_retry("intent")
    prompt = _intent_clarifier_prompt()
    state.add_system_line(prompt)
    return _twiml_response(gather_for_intent(prompt, voice, language))


def _handle_anything_else(state: CallState, intent: Optional[str], user_input: str) -> Response:
    lowered = user_input.lower().strip()
    if intent == "goodbye" or lowered in {"no", "no thanks", "nah", "nope", "that's all", "nothing else"}:
        return _goodbye(state)
    if intent == "affirm" or lowered in {"yes", "yeah", "yep", "sure"}:
        prompt = _continuation_prompt()
        state.add_system_line(prompt)
        state.awaiting = "intent"
        return _twiml_response(gather_for_intent(prompt, voice, language))
    if intent in {"hours", "address", "prices", "booking"}:
        state.awaiting = "intent"
        return _handle_intent(state, intent, user_input)
    prompt = _intent_clarifier_prompt()
    state.add_system_line(prompt)
    state.awaiting = "intent"
    return _twiml_response(gather_for_intent(prompt, voice, language))


def _record_call_summary(call_sid: str, state: CallState, form_data) -> None:
    transcript_path = save_transcript(call_sid, state.transcript)
    state.transcript_file = str(transcript_path)
    if state.intent == "booking" and state.requested_time:
        append_booking(call_sid, state.caller_name, state.requested_time)

    summary = {
        "call_sid": call_sid,
        "finished_at": datetime.now(tz=timezone.utc).isoformat(),
        "direction": form_data.get("Direction") or state.metadata.get("direction"),
        "from": form_data.get("From") or state.metadata.get("from"),
        "to": form_data.get("To") or state.metadata.get("to"),
        "duration_sec": int(form_data.get("CallDuration") or state.metadata.get("duration") or 0),
        "caller_name": state.caller_name,
        "intent": state.intent or "unknown",
        "requested_time": state.requested_time,
        "transcript_file": str(transcript_path),
    }
    append_call_record(summary)


@app.post("/voice")
async def voice_webhook(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    if not call_sid:
        logger.warning("CallSid missing on /voice request")
        return _goodbye(CallState(call_sid="unknown"))

    state = state_store.get_or_create(call_sid)
    if not state.has_greeted:
        _reset_state(state, form)
        prompt = _initial_prompt()
        state.add_system_line(prompt)
        state.has_greeted = True
        logger.info("Incoming call", extra={"call_sid": call_sid})
        return _twiml_response(gather_for_intent(prompt, voice, language))

    if not state.prompted_after_greeting and state.awaiting == "intent":
        prompt = _initial_reprompt()
        state.add_system_line(prompt)
        state.prompted_after_greeting = True
        logger.info("Silence after greeting", extra={"call_sid": call_sid})
        return _twiml_response(gather_for_intent(prompt, voice, language))

    stage = state.awaiting if state.awaiting in {"anything_else", "name", "time"} else "intent"
    return _handle_silence(state, stage)


@app.post("/gather-intent")
async def gather_intent_route(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    if not call_sid:
        logger.warning("CallSid missing on /gather-intent")
        return _goodbye(CallState(call_sid="unknown"))

    state = state_store.get_or_create(call_sid)
    speech_result = (form.get("SpeechResult") or "").strip()
    user_input = speech_result

    if not user_input:
        stage = state.awaiting if state.awaiting in {"anything_else", "name", "time"} else "intent"
        return _handle_silence(state, stage)

    state.add_caller_line(user_input)
    state.reset_silence()

    intent = parse_intent(speech_result)
    logger.info(
        "Parsed caller intent",
        extra={"call_sid": call_sid, "intent": intent, "stage": state.awaiting},
    )

    if state.awaiting == "anything_else":
        return _handle_anything_else(state, intent, user_input)

    state.awaiting = "intent"
    return _handle_intent(state, intent, user_input)


@app.post("/gather-booking")
async def gather_booking_route(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    if not call_sid:
        logger.warning("CallSid missing on /gather-booking")
        return _goodbye(CallState(call_sid="unknown"))

    state = state_store.get_or_create(call_sid)
    speech_result = (form.get("SpeechResult") or "").strip()
    user_input = speech_result

    if not user_input:
        stage = state.awaiting if state.awaiting in {"name", "time"} else "intent"
        return _handle_silence(state, stage)

    state.add_caller_line(user_input)
    state.reset_silence()

    intent = parse_intent(speech_result)

    if state.awaiting == "name":
        if intent == "goodbye":
            return _goodbye(state)
        if intent in {"hours", "address", "prices"}:
            state.awaiting = "intent"
            return _handle_intent(state, intent, user_input)
        if intent == "affirm":
            prompt = _name_clarifier_prompt()
            state.add_system_line(prompt)
            return _twiml_response(gather_for_name(prompt, voice, language))
        name = _extract_name(user_input)
        if not name:
            state.bump_retry("name")
            prompt = _name_clarifier_prompt()
            state.add_system_line(prompt)
            return _twiml_response(gather_for_name(prompt, voice, language))
        state.caller_name = name
        return _ask_for_time(state)

    if state.awaiting == "time":
        if intent == "goodbye":
            return _goodbye(state)
        if intent in {"hours", "address", "prices"}:
            state.awaiting = "intent"
            return _handle_intent(state, intent, user_input)
        if intent == "affirm":
            prompt = _time_clarifier_prompt()
            state.add_system_line(prompt)
            return _twiml_response(gather_for_time(prompt, voice, language))
        state.requested_time = user_input
        state.reset_retries("time")
        return _confirm_booking(state)

    return _handle_intent(state, intent, user_input)


@app.post("/status")
async def status_callback(request: Request) -> JSONResponse:
    form = await request.form()
    call_sid = form.get("CallSid")
    call_status = (form.get("CallStatus") or "").lower()

    logger.info("Status callback", extra={"call_sid": call_sid, "status": call_status})

    if not call_sid:
        return JSONResponse({"ok": True})

    state = state_store.get(call_sid)
    if state:
        state.metadata.update(
            {
                "direction": form.get("Direction") or state.metadata.get("direction"),
                "from": form.get("From") or state.metadata.get("from"),
                "to": form.get("To") or state.metadata.get("to"),
                "duration": form.get("CallDuration") or state.metadata.get("duration"),
            }
        )

    if call_status == "completed":
        if call_sid in completed_calls:
            return JSONResponse({"ok": True})
        completed_calls.add(call_sid)
        state = state_store.remove(call_sid) or CallState(call_sid=call_sid)
        _record_call_summary(call_sid, state, form)

    return JSONResponse({"ok": True})


__all__ = ["app"]
