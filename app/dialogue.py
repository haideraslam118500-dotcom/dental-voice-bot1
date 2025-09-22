from __future__ import annotations

import logging
import random
from typing import Optional

from app import nlp, schedule


log = logging.getLogger("app.dialogue")


GREETINGS = [
    "Hi, thanks for calling Oak Dental. How can I help today?",
    "Hello, Oak Dental here — what can I do for you?",
    "Oak Dental, good to hear from you. Do you need our hours, prices, or a booking?",
]

DISCLAIMER_LINE = "Just so you know, I’m your AI receptionist, not a medical professional."

SILENCE_REPROMPT = (
    "Hello, I’m still on the line. Let me know if you’d like our opening hours, our address, our "
    "prices, or to book an appointment."
)

HOLDERS = [
    "Okay, that's fine.",
    "Yeah, sure.",
    "Right, I understand.",
    "Lovely, thanks.",
    "No worries.",
    "Brilliant.",
    "Sure thing.",
    "Absolutely.",
    "That's alright.",
    "All good.",
    "Great stuff.",
    "Perfect.",
    "Grand.",
]

CLARIFIERS = [
    "Sorry, could you say that again?",
    "I didn't quite catch that.",
    "Mind repeating that for me?",
    "Just checking, are you after our hours, address, prices, or a booking?",
    "Could you let me know if you need hours, address, prices, or to book in?",
    "I'm still here, could you repeat that?",
    "Would you mind saying that one more time?",
    "I want to be sure I heard you right, was it about hours, address, prices, or booking?",
    "Apologies, the line dipped for a second. What do you need today?",
    "Do you need help with hours, address, prices, or a booking?",
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
    "Okay, thanks for calling — have a lovely day. Goodbye.",
    "Alright, I appreciate the call. Take care, goodbye.",
    "Thanks for calling. Have a great day. Goodbye.",
]

CONFIRM_TEMPLATES = [
    "Perfect, I’ll book you for {date} at {time} for a {type}, under {name}.",
    "Alright, {name}, you’re set for {type} on {date} at {time}.",
    "Got it — {type} appointment for {name}, {date} {time}.",
]

HOURS_LINE = (
    "We're open Monday to Friday, nine till five; Saturdays ten till two; Sundays closed."
)
ADDRESS_LINE = "We're at 12 Market Street, Central Milton Keynes, MK9 3QA."
PRICES_LINE = (
    "A checkup starts from sixty pounds, hygiene from seventy-five, and white fillings from one hundred and twenty."
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
            return (
                "Sorry, no free times that day. "
                f"The next available is {next_avail['date']} at {next_avail['start_time']}. Would you like that?"
            )
        options = ", ".join(slot["start_time"] for slot in avail)
        state["stage"] = "ask_time"
        return f"On {parsed}, we have {options}. Which time works for you?"

    if state["stage"] == "ask_time":
        hhmm = nlp.normalize_time(transcript)
        if not hhmm:
            return "What time suits you? You can say ten a m, ten thirty, or three p m."
        avail = {slot["start_time"] for slot in schedule.list_available(date=state.get("date"))}
        if hhmm not in avail:
            sample = sorted(avail)[:3]
            hint = ", ".join(sample) if sample else "no free times"
            return f"Sorry, {hhmm} isn’t free. Times available are {hint}. Which would you like?"
        state["time"] = hhmm
        state["stage"] = "ask_name"
        return f"Okay, {state['time']} noted. And your name please?"

    if state["stage"] == "ask_name":
        state["name"] = (transcript or "").strip()
        state["stage"] = "confirm"
        return f"Great, {state['name']}. Shall I book you for {state['appt_type']} on {state['date']} at {state['time']}?"

    if state["stage"] == "confirm":
        if (transcript or "").lower().strip() in {"yes", "yeah", "yep", "ok", "okay", "please", "sure"}:
            ok = schedule.reserve_slot(state["date"], state["time"], state["name"], state["appt_type"])
            if ok:
                msg = random.choice(CONFIRM_TEMPLATES).format(
                    date=state["date"], time=state["time"], type=state["appt_type"], name=state["name"]
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
            return f"That day looks full. The next available is {nxt['date']} at {nxt['start_time']}. Would you like that?"
        return "Sorry, I can’t see any free times right now."
    options = ", ".join(slot["start_time"] for slot in avail[:6])
    state.clear()
    state["stage"] = "ask_time"
    state["date"] = date
    return f"On {date}, we have {options}. Which time works for you?"

