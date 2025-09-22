from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from twilio.request_validator import RequestValidator

from app.config import get_settings
from app.intent import parse_intent
from app.logging_config import setup_logging
from app.persistence import ensure_schema, persist_call_summary
from app.security import TwilioRequestValidationMiddleware
from app.state import CallState, CallStateStore
from app.twiml import (
    gather_booking,
    gather_first_name,
    gather_intent as gather_intent_twiml,
    respond_with_booking_confirmation,
    respond_with_escalation,
    respond_with_information,
)

logger = logging.getLogger(__name__)

settings = get_settings()
setup_logging(settings.debug_log_json)
ensure_schema(settings.calls_db_path)

voice = settings.preferred_voice or settings.fallback_voice
language = settings.language

state_store = CallStateStore()

validator = (
    RequestValidator(settings.twilio_auth_token) if settings.twilio_auth_token else None
)

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


def _extract_first_name(speech_result: Optional[str]) -> Optional[str]:
    if not speech_result:
        return None
    cleaned = speech_result.strip().split()
    if not cleaned:
        return None
    name = cleaned[0]
    return name.capitalize()


@app.post("/voice")
async def voice_webhook(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    if not call_sid:
        logger.warning("CallSid missing on /voice request")
        return _twiml_response(respond_with_escalation(voice, language))

    state = state_store.get_or_create(call_sid)
    logger.info("Incoming call", extra={"call_sid": call_sid})
    state.name_attempts = 0
    state.intent_attempts = 0
    state.booking_attempts = 0
    state.caller_name = None
    state.intent = None
    state.requested_time = None

    twiml = gather_first_name(state.name_attempts, voice, language)
    return _twiml_response(twiml)


@app.post("/gather-intent")
async def gather_intent(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    if not call_sid:
        logger.warning("CallSid missing on /gather-intent")
        return _twiml_response(respond_with_escalation(voice, language))

    state = state_store.get_or_create(call_sid)
    speech_result = form.get("SpeechResult")
    digits = form.get("Digits")

    if not state.caller_name:
        name = _extract_first_name(speech_result)
        if name:
            state.caller_name = name
            state.name_attempts = 0
            state.intent_attempts = 0
            logger.info(
                "Captured caller name",
                extra={"call_sid": call_sid, "caller_name": state.caller_name},
            )
            twiml = gather_intent_twiml(state.caller_name, state.intent_attempts, voice, language)
            return _twiml_response(twiml)

        state.name_attempts += 1
        if state.name_attempts >= 3:
            logger.info("Failed to capture caller name after retries", extra={"call_sid": call_sid})
            state.intent = state.intent or "unresolved"
            twiml = respond_with_escalation(voice, language)
            return _twiml_response(twiml)

        twiml = gather_first_name(state.name_attempts, voice, language)
        return _twiml_response(twiml)

    intent = parse_intent(speech_result, digits)
    if intent:
        state.intent = intent
        state.intent_attempts = 0
        logger.info("Captured intent", extra={"call_sid": call_sid, "intent": intent})
        if intent == "booking":
            state.booking_attempts = 0
            twiml = gather_booking(state.booking_attempts, voice, language)
            return _twiml_response(twiml)
        state.requested_time = None
        twiml = respond_with_information(intent, voice, language, state.caller_name)
        return _twiml_response(twiml)

    state.intent_attempts += 1
    if state.intent_attempts >= 3:
        logger.info("Failed to capture intent after retries", extra={"call_sid": call_sid})
        state.intent = state.intent or "unresolved"
        twiml = respond_with_escalation(voice, language)
        return _twiml_response(twiml)

    twiml = gather_intent_twiml(state.caller_name or "there", state.intent_attempts, voice, language)
    return _twiml_response(twiml)


@app.post("/gather-booking")
async def gather_booking_route(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    if not call_sid:
        logger.warning("CallSid missing on /gather-booking")
        return _twiml_response(respond_with_escalation(voice, language))

    state = state_store.get_or_create(call_sid)
    speech_result = form.get("SpeechResult")
    digits = form.get("Digits")

    requested_time = speech_result or digits
    if requested_time:
        state.requested_time = requested_time.strip()
        logger.info(
            "Captured booking request",
            extra={
                "call_sid": call_sid,
                "requested_time": state.requested_time,
                "caller_name": state.caller_name,
            },
        )
        twiml = respond_with_booking_confirmation(
            state.requested_time, voice, language, state.caller_name
        )
        return _twiml_response(twiml)

    state.booking_attempts += 1
    if state.booking_attempts >= 3:
        logger.info("Failed to capture booking time after retries", extra={"call_sid": call_sid})
        twiml = respond_with_escalation(voice, language)
        return _twiml_response(twiml)

    twiml = gather_booking(state.booking_attempts, voice, language)
    return _twiml_response(twiml)


@app.post("/status")
async def status_callback(request: Request) -> JSONResponse:
    form = await request.form()
    call_sid = form.get("CallSid")
    call_status = (form.get("CallStatus") or "").lower()

    logger.info("Status callback", extra={"call_sid": call_sid, "status": call_status})

    if call_sid and call_status == "completed":
        state = state_store.remove(call_sid) or CallState(call_sid=call_sid)
        persist_call_summary(
            settings.calls_db_path,
            call_sid,
            state.caller_name,
            state.intent,
            state.requested_time,
        )

    return JSONResponse({"ok": True})


__all__ = ["app"]
