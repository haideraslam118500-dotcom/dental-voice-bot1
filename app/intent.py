from __future__ import annotations

import re
from typing import Optional

_INTENT_KEYWORDS = {
    "hours": {"hours", "open", "opening", "closing"},
    "address": {"address", "where", "located", "location", "find", "directions"},
    "prices": {"price", "prices", "cost", "fee", "fees", "charges", "how much"},
    "booking": {
        "book",
        "booking",
        "appointment",
        "schedule",
        "reserve",
        "checkup",
        "see the dentist",
        "visit",
    },
}

_AVAILABILITY_PATTERNS = {
    "availability",
    "available",
    "what do you have",
    "what have you got",
    "what times",
    "times are available",
    "free slots",
    "free time",
    "free appointment",
    "open slots",
    "what can you do tomorrow",
    "what can you do on",
    "any slots",
    "any availability",
    "today",
    "tomorrow",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
}

_GOODBYE_KEYWORDS = {
    "bye",
    "goodbye",
    "bye bye",
    "bye-bye",
    "no thanks",
    "no thank you",
    "that's all",
    "thats all",
    "nothing else",
    "all good",
    "we're good",
    "were good",
    "that is all",
    "cheers that's all",
    "cheers, that's all",
}

_AFFIRM_KEYWORDS = {
    "yes",
    "yeah",
    "yep",
    "sure",
    "please",
    "ok",
    "okay",
    "alright",
    "sounds good",
}

def parse_intent(speech: Optional[str]) -> Optional[str]:
    if not speech:
        return None

    text = speech.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    words = set(text.split())

    def _contains(keyword: str) -> bool:
        return keyword in text if " " in keyword else keyword in words

    booking_keywords = _INTENT_KEYWORDS.get("booking", set())
    if any(_contains(keyword) for keyword in booking_keywords):
        return "booking"

    hours_keywords = _INTENT_KEYWORDS.get("hours", set())
    if any(_contains(keyword) for keyword in hours_keywords):
        return "hours"

    for keyword in _GOODBYE_KEYWORDS:
        if _contains(keyword):
            return "goodbye"

    for keyword in _AFFIRM_KEYWORDS:
        if _contains(keyword):
            return "affirm"

    if any(pattern in text for pattern in _AVAILABILITY_PATTERNS):
        return "availability"

    for intent, keywords in _INTENT_KEYWORDS.items():
        if intent in {"booking", "hours"}:
            continue
        if any(_contains(keyword) for keyword in keywords):
            return intent
    return None


def extract_appt_type(text: str) -> Optional[str]:
    """Heuristic helper to detect an appointment type mentioned inline."""

    lowered = (text or "").lower()
    if not lowered:
        return None

    types = ["check-up", "check up", "hygiene", "whitening", "filling", "emergency"]
    for raw in types:
        if raw in lowered:
            normalized = raw.replace("check up", "check-up").title()
            if normalized.startswith("Check"):
                return "Check-up"
            return normalized
    return None


__all__ = ["parse_intent", "extract_appt_type"]
