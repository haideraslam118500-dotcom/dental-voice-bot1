from __future__ import annotations

import logging
import random
import re
from collections import deque
from datetime import datetime, timezone
from itertools import cycle
from threading import Lock
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple, Union

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from twilio.twiml.voice_response import VoiceResponse

from app.config import get_settings
from app import nlp, schedule
from app.dialogue import (
    CONFIRM_TEMPLATES,
    DISCLAIMER_LINE,
    GREETINGS,
    THINKING_FILLERS,
    describe_day,
    format_slot_time,
    pick_clarifier,
    pick_holder,
    pick_name_clarifier,
)
from app.intent import extract_appt_type, classify_with_slots
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
MAX_SPEECH_CHARS = 110
CONSENT_LINE = (
    "By providing your number, you agree to receive appointment confirmations and reminders."
)

_voice_lock = Lock()
_active_voice = VOICE
_voice_fallback_notified = False

_greeting_lock = Lock()
_greeting_queue: deque[str] = deque()

MENU_STATEMENT = "I can help with our hours, address, prices, or book you in."
CLARIFY_PROMPT = "I didn’t quite catch that — would you like our hours, address, prices, or to book an appointment?"
ANYTHING_ELSE_PROMPT = "Is there anything else I can help you with?"
BOOKING_TIME_PROMPT = "Sure, let's find you a time. What day and time works for you?"
BOOKING_NAME_PROMPT = "What's the name for the appointment?"
BOOKING_NAME_REPROMPT = "Sorry, could I take the name for the appointment?"
BOOKING_TIME_PROMPT_TEMPLATE = "Thanks {name}. What day and time works for you?"
BOOKING_TIME_REPROMPT = "What day and time would you like to come in?"
BOOKING_CONFIRM_REPROMPT = "Should I pencil that appointment in for you?"
BOOKING_DECLINED_PROMPT = (
    "No problem, we won't lock anything in just yet. Is there anything else I can help you with?"
)

SOFT_REPROMPTS = [
    "Could you say that again?",
    "Pardon — one more time?",
    "Sorry, repeat that for me?",
]

INFO_LINES = {
    "hours": settings.practice.hours,
    "address": settings.practice.address,
    "prices": settings.practice.prices,
}

SERVICE_INFO: Dict[str, str] = {}
for _service_key, _service_value in (settings.practice.service_prices or {}).items():
    lowered = _service_key.lower()
    SERVICE_INFO[lowered] = _service_value
    SERVICE_INFO[lowered.replace("-", "")] = _service_value
    SERVICE_INFO[lowered.replace(" ", "")] = _service_value

SERVICE_KEY_TO_APPT = {
    "check-up": "Check-up",
    "hygiene": "Hygiene",
    "whitening": "Whitening",
    "extraction": "Extraction",
}

APPT_TO_SERVICE_KEY = {v: k for k, v in SERVICE_KEY_TO_APPT.items()}

GOODBYES = [
    "Okay, thanks for calling. Have a lovely day. Goodbye.",
    "Alright, appreciate the call. Take care — goodbye.",
    "Thanks for calling Oak Dental. Bye for now.",
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

ANYTIME_PHRASES = {
    "anytime",
    "any time",
    "any time works",
    "anytime works",
    "anytime is fine",
    "any time is fine",
    "any is fine",
    "whenever",
    "whenever works",
    "whenever is fine",
    "any time works for me",
    "anytime works for me",
    "whenever works for me",
    "whatever time works",
}


PromptSegment = Tuple[str, str]
PromptPayload = Union[str, Sequence[PromptSegment]]


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


def _say_segments(
    say_callable: Callable[[str, Optional[str], Optional[str]], Any],
    message: str,
    *,
    voice: str,
    language: str,
    call_sid: Optional[str] = None,
) -> None:
    segments = nlp.split_for_speech(message, max_len=MAX_SPEECH_CHARS)
    if not segments:
        cleaned = (message or "").strip()
        if not cleaned:
            return
        segments = [cleaned]
    current_voice = voice
    for segment in segments:
        text = (segment or "").strip()
        if not text:
            continue
        _say_with_voice(
            say_callable,
            text,
            preferred_voice=current_voice,
            language=language,
            call_sid=call_sid,
        )
        current_voice = _get_active_voice()


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
        "ending": False,
        "consent_said": False,
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


def _next_opening_line() -> str:
    with _greeting_lock:
        if not _greeting_queue:
            options = list(GREETINGS)
            random.shuffle(options)
            _greeting_queue.extend(options)
        return _greeting_queue.popleft()


def _build_opening_prompt(state: Dict[str, Any]) -> str:
    greeting = state.get("opening_line") or _next_opening_line()
    state.setdefault("opening_line", greeting)
    parts = [greeting]
    if not state.get("disclaimer_said") and DISCLAIMER_LINE:
        parts.append(DISCLAIMER_LINE)
        state["disclaimer_said"] = True
    if not state.get("menu_said") and MENU_STATEMENT:
        parts.append(MENU_STATEMENT)
        state["menu_said"] = True
    return " ".join(part for part in parts if part)


def create_gather_twiml(
    prompt: PromptPayload,
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
    if isinstance(prompt, str):
        _say_segments(
            gather.say,
            prompt,
            voice=voice,
            language=language,
            call_sid=call_sid,
        )
    else:
        for kind, value in prompt:
            if kind == "say":
                _say_segments(
                    gather.say,
                    value,
                    voice=voice,
                    language=language,
                    call_sid=call_sid,
                )
            elif kind == "pause":
                gather.pause(length=value)
    return str(response)


def create_goodbye_twiml(
    message: str,
    *,
    voice: str,
    language: str,
    call_sid: Optional[str] = None,
) -> str:
    response = VoiceResponse()
    _say_segments(
        response.say,
        message,
        voice=voice,
        language=language,
        call_sid=call_sid,
    )
    response.pause(length="0.4")
    response.hangup()
    return str(response)


def _hangup_only_response() -> Response:
    response = VoiceResponse()
    response.hangup()
    return _twiml_response(str(response))


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


def _prompt_to_text(prompt: PromptPayload) -> str:
    if isinstance(prompt, str):
        return prompt
    return " ".join(part for kind, part in prompt if kind == "say")


def _with_ack(text: str, chance: float = 0.7) -> str:
    if not text or chance <= 0:
        return text
    if random.random() >= chance:
        return text
    holder = pick_holder().strip()
    if not holder:
        return text
    return f"{holder} {text}"


def _lookup_service_price(service_key: Optional[str]) -> Optional[str]:
    if not service_key:
        return None
    lowered = service_key.lower()
    for key in {lowered, lowered.replace("-", ""), lowered.replace(" ", "")}:
        if key in SERVICE_INFO:
            return SERVICE_INFO[key]
    return None


def _respond_with_price_details(state: Dict[str, Any], service_key: str) -> Response:
    info_text = _lookup_service_price(service_key) or INFO_LINES["prices"]
    follow_up = "Would you like to book that?"
    message = f"{info_text} {follow_up}".strip()
    payload = nlp.maybe_prefix_with_filler(_with_ack(message, 0.85), THINKING_FILLERS, chance=0.4)
    state["intent"] = "prices"
    state["stage"] = "follow_up"
    state["retries"] = 0
    state["last_service"] = service_key
    state.pop("awaiting_price_service", None)
    return _respond_with_gather(state, payload)


def _prompt_for_service_choice(state: Dict[str, Any]) -> Response:
    question = "Which treatment did you have in mind — check-up, hygiene, whitening, or extraction?"
    prompt = _with_ack(question, 0.75)
    state["awaiting_price_service"] = True
    state["intent"] = "prices"
    state["stage"] = "follow_up"
    return _respond_with_gather(state, prompt)


def _handle_price_service_follow_up(state: Dict[str, Any], user_input: str) -> Response:
    service_key = nlp.detect_service(user_input)
    if service_key:
        return _respond_with_price_details(state, service_key)
    apology = "Sorry, was that for check-up, hygiene, whitening, or extraction?"
    prompt = _with_ack(apology, 0.7)
    state["awaiting_price_service"] = True
    state["stage"] = "follow_up"
    return _respond_with_gather(state, prompt)


def _clarifier_prompt(confidence: Optional[float]) -> str:
    low_confidence = confidence is not None and confidence < 0.6
    if low_confidence:
        clarifier = pick_clarifier() or CLARIFY_PROMPT
        return _with_ack(clarifier, 0.7)
    prompt = random.choice(SOFT_REPROMPTS)
    return _with_ack(prompt, 0.6)


def _respond_with_gather(
    state: Dict[str, Any],
    prompt: PromptPayload,
    *,
    action: str = "/gather-intent",
    hints: Optional[str] = None,
) -> Response:
    _remember_agent_line(state, _prompt_to_text(prompt))
    timeout = settings.practice.no_speech_timeout or 5
    twiml = create_gather_twiml(
        prompt,
        action=action,
        voice=_get_active_voice(),
        language=LANGUAGE,
        hints=hints,
        timeout=int(timeout),
        call_sid=state.get("call_sid"),
    )
    return _twiml_response(twiml)


def _respond_with_goodbye(state: Dict[str, Any]) -> Response:
    message = _next_goodbye()
    _remember_agent_line(state, message)
    state["stage"] = "completed"
    state["ending"] = True
    logger.info(
        "Ending call",
        extra={"call_sid": state.get("call_sid"), "goodbye_text": message},
    )
    return _twiml_response(
        create_goodbye_twiml(
            message,
            voice=_get_active_voice(),
            language=LANGUAGE,
            call_sid=state.get("call_sid"),
        )
    )


def _booking_type_prompt() -> str:
    return _with_ack(
        "What type of appointment would you like? For example check-up, hygiene, whitening, or extraction?",
        0.85,
    )


def _booking_type_reprompt() -> str:
    return _with_ack(
        "We can do check-up, hygiene, whitening, extraction, filling, or emergency. Which would you like?",
        0.85,
    )


def _booking_date_prompt(appt_type: str) -> str:
    return _with_ack(f"Great, a {appt_type} — what day works best for you?", 0.85)


def _booking_date_reprompt() -> str:
    return _with_ack(
        "Which day works best for you? You can say tomorrow or a weekday like Wednesday.",
        0.8,
    )


def _format_times(slots: Sequence[str]) -> str:
    if not slots:
        return ""
    spoken = []
    for slot in slots:
        if not slot:
            continue
        spoken.append(f"{nlp.human_time_phrase(slot)} at {slot}")
    if not spoken:
        return ""
    if len(spoken) == 1:
        return spoken[0]
    if len(spoken) == 2:
        return " or ".join(spoken)
    return ", ".join(spoken[:-1]) + f", or {spoken[-1]}"


def _booking_time_prompt(date: str, slots: Sequence[str]) -> PromptPayload:
    joined = _format_times(list(slots))
    if not joined:
        message = _with_ack(
            "I couldn't see any free times on that day. Would another day work?",
            0.7,
        )
        return nlp.maybe_prefix_with_filler(message, THINKING_FILLERS, chance=0.5)
    pretty_day = nlp.human_day_phrase(date)
    base = _with_ack(f"On {date}, {pretty_day}, we have {joined}. Which time works for you?", 0.9)
    return nlp.maybe_prefix_with_filler(base, THINKING_FILLERS, chance=0.8)


def _booking_time_reprompt(slots: Sequence[str]) -> PromptPayload:
    cleaned = [f"{nlp.human_time_phrase(slot)} at {slot}" for slot in slots if slot]
    if cleaned:
        preview = ", ".join(cleaned[:3])
        prompt = f"Times available are {preview}. Which would you like?"
    else:
        prompt = "What time suits you? You can say nine a m, eleven a m, or two thirty p m."
    clarifier = pick_clarifier()
    if clarifier:
        prompt = f"{clarifier} {prompt}"
    prompt = _with_ack(prompt, 0.7)
    return nlp.maybe_prefix_with_filler(prompt, THINKING_FILLERS, chance=0.5)


def _booking_name_prompt(time: str) -> str:
    base = f"Okay, {nlp.hhmm_to_12h(time)} noted. And your name please?"
    return _with_ack(base, 0.75)


def _booking_confirm_prompt(state: Dict[str, Any]) -> PromptPayload:
    booking_date = state.get("booking_date")
    booking_time = state.get("booking_time")
    if booking_date and booking_time:
        when_text = format_slot_time(booking_date, booking_time)
        connector = "on"
    elif booking_date:
        when_text = nlp.human_day_phrase(booking_date)
        connector = "on"
    elif booking_time:
        when_text = nlp.human_time_phrase(booking_time)
        connector = "at"
    else:
        when_text = "the time we discussed"
        connector = "at"
    message = (
        f"Great, {state['caller_name']}. Shall I book you in for {state['booking_appt_type']} "
        f"{connector} {when_text}?"
    )
    message = _with_ack(message, 0.7)
    return nlp.maybe_prefix_with_filler(message, THINKING_FILLERS, chance=0.6)


def _booking_confirmed_message(state: Dict[str, Any]) -> PromptPayload:
    date_value = state.get("booking_date")
    human_date = nlp.human_day_phrase(date_value) if date_value else ""
    time_value = state.get("booking_time")
    human_time = nlp.human_time_phrase(time_value) if time_value else ""
    msg = random.choice(CONFIRM_TEMPLATES).format(
        date=human_date or (date_value or ""),
        time=human_time or (time_value or ""),
        type=state["booking_appt_type"],
        name=state["caller_name"] or "",
    )
    parts: list[PromptSegment] = []
    parts.append(("say", _with_ack(msg, 0.6)))
    if not state.get("consent_said"):
        parts.append(("say", CONSENT_LINE))
        state["consent_said"] = True
    parts.append(("say", _with_ack(ANYTHING_ELSE_PROMPT, 0.6)))
    return parts


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
    inline = extract_appt_type(text)
    if inline:
        return inline
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
        prompt = nlp.maybe_prefix_with_filler(
            _with_ack(
                "Which day are you thinking of? You can say tomorrow or a weekday like Wednesday.",
                0.85,
            ),
            THINKING_FILLERS,
            chance=0.6,
        )
        return _respond_with_gather(state, prompt, action="/gather-booking")

    slots = _available_slots_for_date(date)
    if not slots:
        nxt = _next_available_slot()
        if nxt:
            message = _with_ack(
                f"That day looks full. The next available is {describe_day(nxt['date'])} at {nlp.hhmm_to_12h(nxt['start_time'])}. Would you like that?",
                0.75,
            )
        else:
            message = _with_ack("Sorry, I can’t see any free times right now.", 0.7)
        state["booking_date"] = date
        state["booking_available_times"] = []
        state["stage"] = "booking_date"
        state["silence_count"] = 0
        state["retries"] = 0
        return _respond_with_gather(
            state,
            nlp.maybe_prefix_with_filler(message, THINKING_FILLERS, chance=0.6),
            action="/gather-booking",
        )

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
    reprompt: PromptPayload,
    action: str = "/gather-intent",
) -> Response:
    state["silence_count"] = state.get("silence_count", 0) + 1
    state["retries"] = state.get("retries", 0) + 1
    logger.info(
        "Silence detected",
        extra={"call_sid": state.get("call_sid"), "count": state["silence_count"], "stage": state.get("stage")},
    )
    max_reprompts = max(int(settings.practice.max_silence_reprompts or 1), 1)
    if state["silence_count"] <= max_reprompts:
        prompt = reprompt
        if isinstance(prompt, str):
            if prompt == CLARIFY_PROMPT:
                clarifier = pick_clarifier()
                if clarifier:
                    prompt = _with_ack(clarifier, 0.7)
                else:
                    prompt = _with_ack(prompt, 0.6)
            else:
                prompt = _with_ack(prompt, 0.65)
        return _respond_with_gather(state, prompt, action=action)
    return _respond_with_goodbye(state)


def _start_booking(state: Dict[str, Any], initial_text: Optional[str] = None) -> Response:
    _reset_booking_context(state)
    state["silence_count"] = 0
    state["retries"] = 0

    detected_service = nlp.detect_service(initial_text or "") or state.get("last_service")
    inline_type = extract_appt_type(initial_text or "")
    if not inline_type and detected_service:
        inline_type = SERVICE_KEY_TO_APPT.get(detected_service)
    if inline_type:
        state["booking_appt_type"] = inline_type
        mapped_service = APPT_TO_SERVICE_KEY.get(inline_type)
        if mapped_service:
            state["last_service"] = mapped_service
        elif detected_service:
            state["last_service"] = detected_service
        state["stage"] = "booking_date"
        logger.info(
            "Booking flow started",
            extra={"call_sid": state.get("call_sid"), "prefill_type": inline_type},
        )
        return _respond_with_gather(state, _booking_date_prompt(inline_type), action="/gather-booking")

    state["stage"] = "booking_type"
    logger.info("Booking flow started", extra={"call_sid": state.get("call_sid")})
    return _respond_with_gather(state, _booking_type_prompt(), action="/gather-booking")


def _handle_primary_intent(
    state: Dict[str, Any], intent: Optional[str], user_input: str, confidence: Optional[float] = None
) -> Response:
    lowered = user_input.lower().strip()
    if state.get("awaiting_price_service"):
        return _handle_price_service_follow_up(state, user_input)
    if intent == "goodbye" or lowered in NEGATIVE_RESPONSES:
        return _respond_with_goodbye(state)
    if intent == "prices":
        service_key = nlp.detect_service(user_input) or state.get("last_service")
        if service_key:
            return _respond_with_price_details(state, service_key)
        return _prompt_for_service_choice(state)
    if intent in INFO_LINES:
        info_text = INFO_LINES[intent]
        message = _with_ack(f"{info_text} {ANYTHING_ELSE_PROMPT}", 0.85)
        payload = nlp.maybe_prefix_with_filler(message, THINKING_FILLERS, chance=0.4)
        state["intent"] = intent
        state["stage"] = "follow_up"
        state["retries"] = 0
        logger.info("Providing information", extra={"call_sid": state.get("call_sid"), "intent": intent})
        return _respond_with_gather(state, payload)
    if intent == "availability":
        if state.get("intent") != "booking":
            _reset_booking_context(state)
        return _handle_availability_request(state, user_input)
    if intent == "booking":
        return _start_booking(state, user_input)
    if intent == "affirm" or lowered in POSITIVE_RESPONSES:
        state["stage"] = "intent"
        return _respond_with_gather(state, _with_ack(CLARIFY_PROMPT, 0.65))
    state["intent"] = state.get("intent") or "other"
    prompt = _clarifier_prompt(confidence)
    return _respond_with_gather(state, prompt)


def _handle_follow_up(
    state: Dict[str, Any], intent: Optional[str], user_input: str, confidence: Optional[float] = None
) -> Response:
    lowered = user_input.lower().strip()
    if state.get("awaiting_price_service"):
        return _handle_price_service_follow_up(state, user_input)
    if intent == "goodbye" or lowered in NEGATIVE_RESPONSES:
        return _respond_with_goodbye(state)
    if intent == "availability":
        if state.get("intent") != "booking":
            _reset_booking_context(state)
        return _handle_availability_request(state, user_input)
    if intent == "prices":
        service_key = nlp.detect_service(user_input) or state.get("last_service")
        if service_key:
            return _respond_with_price_details(state, service_key)
        return _prompt_for_service_choice(state)
    if intent in INFO_LINES or intent == "booking":
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input, confidence=confidence)
    if intent == "affirm" or lowered in POSITIVE_RESPONSES:
        state["stage"] = "intent"
        return _respond_with_gather(state, _with_ack(CLARIFY_PROMPT, 0.65))
    state["stage"] = "intent"
    prompt = _clarifier_prompt(confidence)
    return _respond_with_gather(state, prompt)


def _handle_booking_type(
    state: Dict[str, Any], user_input: str, intent: Optional[str], confidence: Optional[float] = None
) -> Response:
    if intent == "goodbye":
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input, confidence=confidence)
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


def _handle_booking_date(
    state: Dict[str, Any], user_input: str, intent: Optional[str], confidence: Optional[float] = None
) -> Response:
    lowered = user_input.lower().strip()
    if intent == "goodbye" or lowered in NEGATIVE_RESPONSES:
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input, confidence=confidence)
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
                f"Sorry, no free times on that day. The next available is {describe_day(nxt['date'])} at {nlp.hhmm_to_12h(nxt['start_time'])}. Would you like that?"
            )
        else:
            message = "Sorry, I can’t see any available times in the schedule right now."
        return _respond_with_gather(state, message, action="/gather-booking")

    state["stage"] = "booking_time"
    prompt = _booking_time_prompt(parsed, slots)
    return _respond_with_gather(state, prompt, action="/gather-booking")


def _handle_booking_time(
    state: Dict[str, Any], user_input: str, intent: Optional[str], confidence: Optional[float] = None
) -> Response:
    if intent == "goodbye":
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input, confidence=confidence)
    if intent == "availability":
        return _handle_availability_request(state, user_input)

    available_list = list(state.get("booking_available_times") or [])
    if state.get("booking_date") and not available_list:
        available_list = _available_slots_for_date(state["booking_date"])
        state["booking_available_times"] = available_list
    avail_set = set(available_list)

    if not available_list:
        state["retries"] += 1
        return _respond_with_gather(
            state,
            "Sorry, I can’t see any free times for that day.",
            action="/gather-booking",
        )

    lowered = user_input.lower().strip()
    if lowered in ANYTIME_PHRASES:
        hhmm = available_list[0]
    else:
        direct_pick = nlp.parse_time_like(user_input)
        hhmm = None
        if direct_pick and (not avail_set or direct_pick in avail_set):
            hhmm = direct_pick
        if not hhmm:
            hhmm = nlp.fuzzy_pick_time(user_input, available_list)

    if not hhmm:
        state["retries"] += 1
        return _respond_with_gather(
            state,
            _booking_time_reprompt(available_list),
            action="/gather-booking",
        )

    if avail_set and hhmm not in avail_set:
        state["retries"] += 1
        return _respond_with_gather(
            state,
            _booking_time_reprompt(available_list),
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


def _handle_booking_name(
    state: Dict[str, Any], user_input: str, intent: Optional[str], confidence: Optional[float] = None
) -> Response:
    if intent == "goodbye":
        return _respond_with_goodbye(state)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input, confidence=confidence)
    if intent == "availability":
        return _handle_availability_request(state, user_input)

    name = _extract_first_name(user_input)
    if not name:
        state["retries"] += 1
        attempts = state.get("name_attempts", 0) + 1
        state["name_attempts"] = attempts
        max_attempts = max(int(settings.practice.max_silence_reprompts or 2), 2)
        if attempts > max_attempts:
            logger.info(
                "Name capture failed; ending call",
                extra={"call_sid": state.get("call_sid"), "attempts": attempts},
            )
            state.pop("name_attempts", None)
            return _respond_with_goodbye(state)
        prompt = pick_name_clarifier() or BOOKING_NAME_REPROMPT
        prompt = _with_ack(prompt, 0.7)
        return _respond_with_gather(state, prompt, action="/gather-booking")

    state["caller_name"] = name
    state["stage"] = "booking_confirm"
    state["silence_count"] = 0
    state["retries"] = 0
    state.pop("name_attempts", None)
    logger.info(
        "Captured caller name",
        extra={"call_sid": state.get("call_sid"), "caller_name": name},
    )
    return _respond_with_gather(state, _booking_confirm_prompt(state), action="/gather-booking")


def _handle_booking_confirmation(
    state: Dict[str, Any], user_input: str, intent: Optional[str], confidence: Optional[float] = None
) -> Response:
    lowered = user_input.lower().strip()
    if intent == "goodbye" or lowered in NEGATIVE_RESPONSES:
        state["stage"] = "follow_up"
        return _respond_with_gather(state, BOOKING_DECLINED_PROMPT)
    if intent in INFO_LINES:
        state["stage"] = "intent"
        return _handle_primary_intent(state, intent, user_input, confidence=confidence)
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

    if state.get("ending") or state.get("stage") == "completed":
        return _hangup_only_response()

    speech_result = (form.get("SpeechResult") or "").strip()
    if speech_result:
        transcript_add(call_sid, "Caller", speech_result)

    if not state.get("greeted"):
        state["greeted"] = True
        state["stage"] = "intent"
        state["silence_count"] = 0
        state["retries"] = 0
        logger.info("Incoming call", extra={"call_sid": call_sid})
        return _respond_with_gather(state, _build_opening_prompt(state))

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

    if state.get("ending") or state.get("stage") == "completed":
        return _hangup_only_response()

    speech_result = (form.get("SpeechResult") or "").strip()
    raw_confidence = form.get("Confidence")
    try:
        confidence = float(raw_confidence) if raw_confidence not in (None, "") else None
    except (TypeError, ValueError):
        confidence = None
    if not speech_result:
        reprompt = CLARIFY_PROMPT if state.get("stage") == "intent" else ANYTHING_ELSE_PROMPT
        return _handle_silence(state, reprompt=reprompt)

    _remember_caller_line(state, speech_result)
    state["silence_count"] = 0

    intent, slots = classify_with_slots(speech_result)
    service_slot = slots.get("service")
    if service_slot:
        state["last_service"] = service_slot
    logger.info(
        "Parsed caller input",
        extra={"call_sid": call_sid, "intent": intent, "stage": state.get("stage")},
    )

    if state.get("stage") == "follow_up":
        return _handle_follow_up(state, intent, speech_result, confidence=confidence)
    state["stage"] = "intent"
    return _handle_primary_intent(state, intent, speech_result, confidence=confidence)


@app.post("/gather-booking")
async def gather_booking_route(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    if not call_sid:
        logger.warning("CallSid missing on /gather-booking request")
        return _missing_call_sid_response()

    state = _get_state(call_sid, form)
    assert state is not None

    if state.get("ending") or state.get("stage") == "completed":
        return _hangup_only_response()

    speech_result = (form.get("SpeechResult") or "").strip()
    raw_confidence = form.get("Confidence")
    try:
        confidence = float(raw_confidence) if raw_confidence not in (None, "") else None
    except (TypeError, ValueError):
        confidence = None
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

    intent, slots = classify_with_slots(speech_result)
    service_slot = slots.get("service")
    if service_slot:
        state["last_service"] = service_slot

    if stage == "booking_type":
        return _handle_booking_type(state, speech_result, intent, confidence=confidence)
    if stage == "booking_date":
        return _handle_booking_date(state, speech_result, intent, confidence=confidence)
    if stage == "booking_time":
        return _handle_booking_time(state, speech_result, intent, confidence=confidence)
    if stage == "booking_name":
        return _handle_booking_name(state, speech_result, intent, confidence=confidence)
    if stage == "booking_confirm":
        return _handle_booking_confirmation(state, speech_result, intent, confidence=confidence)

    return _handle_primary_intent(state, intent, speech_result, confidence=confidence)


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
