from __future__ import annotations

import random
from typing import Optional


MENU_GREETING = (
    "Hi, thanks for calling our dental practice. I’m your AI receptionist, here to help with "
    "general information and booking appointments. Please note, I’m not a medical professional. "
    "You can ask about our opening hours, our address, our prices, or say you’d like to book an "
    "appointment."
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

HOURS_LINE = (
    "We're open Monday to Friday, nine till five; Saturdays ten till two; Sundays closed."
)
ADDRESS_LINE = "We're at 12 Market Street, Central Milton Keynes, MK9 3QA."
PRICES_LINE = (
    "A checkup starts from sixty pounds, hygiene from seventy-five, and white fillings from one hundred and twenty."
)

ANYTHING_ELSE_PROMPT = "Is there anything else I can help you with?"


def build_menu_prompt() -> str:
    return MENU_GREETING


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
    return f"{holder} To get you booked in, could I take the name for the appointment?"


def compose_booking_time_prompt(name: Optional[str]) -> str:
    holder = pick_holder()
    if name:
        return f"Thanks {name}. {holder} What day and time suits you?"
    return f"Thanks. {holder} What day and time suits you?"


def compose_booking_confirmation(name: Optional[str], requested_time: str) -> str:
    holder = pick_holder()
    name_bit = f"Thanks {name}. " if name else "Thanks. "
    return (
        f"{name_bit}{holder} I'll pencil in {requested_time}. We'll give you a ring to confirm. "
        f"{ANYTHING_ELSE_PROMPT}"
    )

