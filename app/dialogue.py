from __future__ import annotations

import calendar
import datetime
import logging
import random
from typing import Optional

from app import nlp, schedule
from app.intent import extract_appt_type
from app.config import PracticeConfig


log = logging.getLogger("app.dialogue")


GREETINGS = [
    "Hi, Oak Dental. How can I help today?",
    "Hello, Oak Dental speaking — how can I help?",
    "Hi there, Oak Dental — what do you need today?",
    "Oak Dental here. How can I help you?",
    "Thanks for calling Oak Dental. What can I do for you?",
    "Hiya, you’ve reached Oak Dental. How can I help?",
    "Good afternoon, Oak Dental speaking. What can I do for you today?",
    "Hello there, Oak Dental. Are you calling to book, or for info?",
]

DISCLAIMER_LINE = "Just so you know, I’m your AI receptionist, not a medical professional."

SILENCE_REPROMPT = (
    "Hello, I’m still on the line. Let me know if you’d like our opening hours, our address, our "
    "prices, or to book an appointment."
)

HOLDERS = [
    "Okay, that's fine.",
    "Yeah, sure.",
    "Hmm, okay.",
    "Right, I understand.",
    "No problem.",
    "Alright.",
    "Got it.",
    "Makes sense.",
    "Absolutely.",
    "Sure thing.",
    "Okay, noted.",
    "All good.",
    "Sounds good.",
    "Okay, let me check.",
    "One moment.",
    "Alright, give me a sec.",
    "Great, thanks.",
    "Lovely, thanks.",
    "No worries.",
    "Let me check that.",
    "Bear with me.",
    "Thanks, just a sec.",
]

CLARIFIERS = [
    "Sorry, could you repeat that in a few words?",
    "I didn’t quite catch that — was that a booking, our hours, or prices?",
    "One more time please — which day did you want?",
    "Could you say that slowly for me?",
    "Sorry, could you say that again?",
    "Mind repeating that for me?",
    "I want to be sure I heard you right, was it about hours, address, prices, or booking?",
    "Apologies, the line dipped for a second. What do you need today?",
]

THINKING_FILLERS = [
    "Okay.",
    "Sure.",
    "Right.",
    "No problem.",
    "All good.",
    "One moment.",
    "Okay, one moment while I check.",
    "Alright, let me have a quick look.",
    "No worries, give me a second.",
    "Right, I’m checking that now.",
    "Okay, let's see what we've got.",
    "Sure, I’m pulling that up.",
]

NAME_CLARIFIERS = [
    "Sorry, who should I pop the booking under?",
    "I missed the name there, could you share it again?",
    "Just the name for the appointment, please?",
    "Could you tell me who the visit is for?",
    "Whose name should I note down for the booking?",
]

TIME_CLARIFIERS = [
    "What day and time works best for you?",
    "When would you like to come in?",
    "Could you tell me the day and time you prefer?",
    "Pop a day and time on it for me?",
    "When suits you for the appointment?",
]

GOODBYES = [
    "Alright, take care and have a lovely day.",
    "Thanks for calling, bye for now.",
    "Speak soon, bye-bye.",
    "Brilliant, have a great day, cheerio.",
    "Take care, we'll chat soon.",
    "Thanks, we'll be in touch, bye now.",
    "Cheers, bye.",
    "All the best, goodbye.",
    "Thanks again, bye bye.",
    "Have a cracking day, goodbye.",
    "Pleasure speaking, take care.",
    "Lovely, talk soon, bye.",
]

CLOSINGS = [
    "Okay, thanks for calling. Have a lovely day. Goodbye.",
    "Alright, appreciate the call. Take care — goodbye.",
    "Thanks for calling Oak Dental. Bye for now.",
]


def greeting(practice: PracticeConfig) -> str:
    name = getattr(practice, "practice_name", "Oak Dental") or "Oak Dental"
    openings = getattr(practice, "openings", None) or GREETINGS
    if openings:
        return openings[0]
    return f"Hi, thanks for calling {name}. How can I help today?"


def info_for_intent(practice: PracticeConfig, intent: str) -> str:
    prices = getattr(practice, "price_items", {}) or {}
    hours = (getattr(practice, "hours", "") or HOURS_LINE).strip()
    address = (getattr(practice, "address", "") or ADDRESS_LINE).strip()

    if intent == "hours":
        return hours or HOURS_LINE
    if intent == "address":
        return address or ADDRESS_LINE
    if intent == "prices":
        price_text = (getattr(practice, "prices", "") or "").strip()
        if price_text:
            return price_text
        if prices:
            return " ".join(value for value in prices.values() if value).strip()
        return PRICES_LINE

    if intent in {
        "mot_info",
        "service_info",
        "tyre_info",
        "diagnostics_info",
        "oil_info",
        "brake_info",
        "quote",
        "recovery",
    }:
        interim = prices.get("interim_service")
        full = prices.get("full_service")
        service_summary = " ".join(part for part in [interim, full] if part) or (
            "Interim service from one-forty-nine. Full service from two-forty-nine."
        )
        mapping = {
            "mot_info": prices.get("mot") or "MOT is fifty-five pounds.",
            "service_info": service_summary,
            "tyre_info": prices.get("tyre") or "Tyres fitted from fifty-five each.",
            "diagnostics_info": prices.get("diagnostics") or "Diagnostics check is sixty pounds.",
            "oil_info": prices.get("oil_change") or "Oil and filter change from eighty-five pounds.",
            "brake_info": prices.get("brake_pads") or "Front brake pads from one-thirty, parts and labour.",
            "quote": (
                prices.get("quote")
                or (
                    "Happy to price that — what car and what’s needed?"
                    if prices
                    else (getattr(practice, "prices", "") or PRICES_LINE)
                )
            ),
            "recovery": prices.get("recovery")
            or "We can help arrange a tow or recovery if you need one.",
        }
        return mapping[intent]

    return ""


def consent_snippet(practice: PracticeConfig) -> str:
    snippets = getattr(practice, "consent_snippets", None) or []
    return (snippets[0] if snippets else "").strip()

CONFIRM_TEMPLATES = [
    "Perfect, I’ll book you for {date} at {time} for a {type}, under {name}.",
    "Alright, {name}, you’re set for {type} on {date} at {time}.",
    "Got it — {type} appointment for {name}, {date} {time}.",
]

HOURS_LINE = (
    "We’re open Monday to Friday nine to five, Saturday nine to one. Closed Sundays and bank holidays."
)
ADDRESS_LINE = "We’re at 12 High Street, Oakford, OX1 2AB. Entrance next to the pharmacy."
PRICES_LINE = (
    "A routine check-up is forty five pounds. Hygiene is sixty five. Whitening starts from two hundred and fifty."
)

ANYTHING_ELSE_PROMPT = "Is there anything else I can help you with?"

CONFIRMATIONS = [
    "Alright, I’ve got {slot}. Shall I go ahead and reserve it?",
    "Okay, booking for {slot}. Does that sound good?",
    "Got it — {slot}. Want me to lock that in?",
]

AVAILABILITY_OPTIONS = [
    "Tomorrow at 10am",
    "Tomorrow at 3pm",
    "Friday at 11am",
]


def describe_day(date: str) -> str:
    try:
        parsed = datetime.datetime.strptime(date, "%Y-%m-%d")
    except Exception:
        return date
    day_name = calendar.day_name[parsed.weekday()]
    month = parsed.strftime("%B")
    day = parsed.day
    suffix = "th"
    if day in {1, 21, 31}:
        suffix = "st"
    elif day in {2, 22}:
        suffix = "nd"
    elif day in {3, 23}:
        suffix = "rd"
    return f"{day_name}, {month} {day}{suffix}"


def format_slot_time(date: str, time: str) -> str:
    spoken_day = describe_day(date)
    spoken_time = nlp.hhmm_to_12h(time) if time else time
    if spoken_time:
        return f"{spoken_day} at {spoken_time}"
    return spoken_day


def build_menu_prompt() -> str:
    return random.choice(GREETINGS)


def compose_disclaimer() -> str:
    return DISCLAIMER_LINE


def compose_initial_reprompt() -> str:
    return SILENCE_REPROMPT


def pick_holder() -> str:
    return random.choice(HOLDERS)


def pick_clarifier() -> str:
    return random.choice(CLARIFIERS)


def pick_thinking_filler() -> str:
    return random.choice(THINKING_FILLERS)


def pick_name_clarifier() -> str:
    return random.choice(NAME_CLARIFIERS)


def pick_time_clarifier() -> str:
    return random.choice(TIME_CLARIFIERS)


def pick_goodbye() -> str:
    return random.choice(GOODBYES)


def info_line(intent: str) -> str:
    mapping = {
        "hours": HOURS_LINE,
        "address": ADDRESS_LINE,
        "prices": PRICES_LINE,
    }
    return mapping[intent]


def compose_info_prompt(intent: str) -> str:
    holder = pick_holder()
    return f"{holder} {info_line(intent)} {ANYTHING_ELSE_PROMPT}"


def compose_anything_else_prompt() -> str:
    holder = pick_holder()
    return f"{holder} {ANYTHING_ELSE_PROMPT}"


def compose_booking_name_prompt() -> str:
    holder = pick_holder()
    return f"{holder} Who should I put the booking under?"


def compose_booking_time_prompt(name: Optional[str]) -> str:
    holder = pick_holder()
    if name:
        return f"Thanks {name}. {holder} What day and time works for you?"
    return f"{holder} What day and time works best for you?"


def compose_booking_confirmation(name: Optional[str], requested_time: str) -> str:
    holder = pick_holder()
    confirmation = random.choice(CONFIRMATIONS).format(slot=requested_time)
    name_bit = f"Thanks {name}. " if name else "Thanks. "
    return f"{name_bit}{holder} {confirmation}"


def booking_flow(state, transcript: str):
    log.info(f"Booking flow stage={state.get('stage')} input={transcript}")

    if state.get("stage") is None:
        state.clear()
        inline_type = extract_appt_type(transcript)
        if inline_type:
            state["appt_type"] = inline_type
            state["stage"] = "ask_date"
            return f"Great, a {inline_type} — what day works best for you?"
        state["stage"] = "ask_type"
        return "Sure, what type of appointment would you like? For example check-up, hygiene, or whitening?"

    if state["stage"] == "ask_type":
        chosen = (transcript or "").strip().lower()
        match = next((t for t in schedule.APPT_TYPES if t.lower() == chosen), None)
        if match is None:
            match = next((t for t in schedule.APPT_TYPES if chosen and chosen in t.lower()), None)
        if not match:
            return f"Sorry, I didn’t catch that type. We do {', '.join(schedule.APPT_TYPES)}. Which would you like?"
        state["appt_type"] = match
        state["stage"] = "ask_date"
        return f"Great, a {match} — what day works best for you?"

    if state["stage"] == "ask_date":
        parsed = nlp.parse_date_phrase(transcript)
        if not parsed:
            return "Which day works best for you? You can say tomorrow or a weekday like Wednesday."
        state["date"] = parsed
        avail = schedule.list_available(date=parsed)
        if not avail:
            next_avail = schedule.find_next_available()
            if not next_avail:
                return "Sorry, I can’t see any available times in the schedule right now."
            speak_next = nlp.human_day_phrase(next_avail["date"])
            return (
                "Sorry, no free times that day. "
                f"The next available is {speak_next} at {nlp.hhmm_to_12h(next_avail['start_time'])}. Would you like that?"
            )
        options = ", ".join(nlp.hhmm_to_12h(slot["start_time"]) for slot in avail)
        state["stage"] = "ask_time"
        speak_day = nlp.human_day_phrase(parsed)
        return f"On {speak_day}, we have {options}. Which time works for you?"

    if state["stage"] == "ask_time":
        avail_slots = [slot["start_time"] for slot in schedule.list_available(date=state.get("date"))]
        if not avail_slots:
            return "Sorry, I can’t see any free times for that day."
        lowered = (transcript or "").strip().lower()
        if lowered in {
            "anytime",
            "any time",
            "whenever",
            "whenever is fine",
            "any time is fine",
            "any is fine",
            "any time works",
            "anytime works",
            "any time works for me",
            "anytime works for me",
            "whenever works",
            "whenever works for me",
            "whatever time works",
        }:
            state["time"] = avail_slots[0]
            state["stage"] = "ask_name"
            return f"Okay, {nlp.hhmm_to_12h(state['time'])} works. And your name please?"
        hhmm = nlp.fuzzy_pick_time(transcript, avail_slots)
        if not hhmm:
            hint = ", ".join(nlp.hhmm_to_12h(t) for t in avail_slots[:4]) if avail_slots else "no free times"
            return f"What time suits you? For example {hint}."
        if hhmm not in avail_slots:
            hint = ", ".join(nlp.hhmm_to_12h(t) for t in avail_slots[:4]) if avail_slots else "no free times"
            return f"Sorry, {nlp.hhmm_to_12h(hhmm)} isn’t free. Times available are {hint}. Which would you like?"
        state["time"] = hhmm
        state["stage"] = "ask_name"
        return f"Okay, {nlp.hhmm_to_12h(state['time'])} noted. And your name please?"

    if state["stage"] == "ask_name":
        state["name"] = (transcript or "").strip()
        state["stage"] = "confirm"
        speak_day = nlp.human_day_phrase(state["date"])
        return f"Great, {state['name']}. Shall I book you for {state['appt_type']} on {speak_day} at {nlp.hhmm_to_12h(state['time'])}?"

    if state["stage"] == "confirm":
        if (transcript or "").lower().strip() in {"yes", "yeah", "yep", "ok", "okay", "please", "sure"}:
            ok = schedule.reserve_slot(state["date"], state["time"], state["name"], state["appt_type"])
            if ok:
                msg = random.choice(CONFIRM_TEMPLATES).format(
                    date=nlp.human_day_phrase(state["date"]),
                    time=nlp.hhmm_to_12h(state["time"]),
                    type=state["appt_type"],
                    name=state["name"],
                )
                state.clear()
                return msg + " Is there anything else I can help you with?"
            state.clear()
            return "Sorry, that slot was just taken. Would you like to pick another?"
        state.clear()
        return "No problem, I won’t reserve it. Is there anything else I can help you with?"

    return "I didn’t quite catch that."


def handle_availability(transcript: str, state) -> str:
    date = nlp.parse_date_phrase(transcript)
    if not date:
        return "Sure — which day are you thinking of? You can say tomorrow or a weekday like Wednesday."
    avail = schedule.list_available(date=date)
    if not avail:
        nxt = schedule.find_next_available()
        if nxt:
            speak_next = nlp.human_day_phrase(nxt["date"])
            return (
                f"That day looks full. The next available is {speak_next} at {nlp.hhmm_to_12h(nxt['start_time'])}."
                " Would you like that?"
            )
        return "Sorry, I can’t see any free times right now."
    options = ", ".join(nlp.hhmm_to_12h(slot["start_time"]) for slot in avail[:6])
    state.clear()
    state["stage"] = "ask_time"
    state["date"] = date
    speak_day = nlp.human_day_phrase(date)
    return f"On {speak_day}, we have {options}. Which time works for you?"

