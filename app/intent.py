from __future__ import annotations

import re
from typing import Optional

_INTENT_KEYWORDS = {
    "hours": {"hours", "open", "opening", "times"},
    "address": {"address", "where", "located", "location", "find"},
    "prices": {"price", "prices", "cost", "fee", "fees"},
    "booking": {"book", "booking", "appointment", "schedule", "reserve"},
}

_DIGIT_INTENT = {
    "1": "hours",
    "2": "address",
    "3": "prices",
    "4": "booking",
}


def parse_intent(speech: Optional[str], digits: Optional[str]) -> Optional[str]:
    if digits:
        for digit in digits:
            intent = _DIGIT_INTENT.get(digit)
            if intent:
                return intent

    if not speech:
        return None

    text = speech.lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return intent
    return None


__all__ = ["parse_intent"]
