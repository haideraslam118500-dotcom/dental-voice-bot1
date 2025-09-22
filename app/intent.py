from __future__ import annotations

import re
from typing import Optional

_INTENT_KEYWORDS = {
    "hours": {"hours", "open", "opening", "times", "time"},
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
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    words = set(text.split())

    def _contains(keyword: str) -> bool:
        return keyword in text if " " in keyword else keyword in words

    for keyword in _GOODBYE_KEYWORDS:
        if _contains(keyword):
            return "goodbye"

    for keyword in _AFFIRM_KEYWORDS:
        if _contains(keyword):
            return "affirm"

    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(_contains(keyword) for keyword in keywords):
            return intent
    return None


__all__ = ["parse_intent"]
