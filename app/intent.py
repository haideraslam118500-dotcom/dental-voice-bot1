from __future__ import annotations

import re
from typing import Iterable, Optional


def _normalize(text: str) -> str:
    text = (text or "").replace("’", "'")
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _lev(a: str, b: str, limit: int = 2) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev = dp[0]
        dp[0] = i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
            prev = cur
    return dp[-1]


def _any_fuzzy(text: str, vocab: Iterable[str], max_dist: int = 1) -> bool:
    tokens = text.split()
    for raw in vocab:
        keyword = (raw or "").replace("’", "'").lower().strip()
        if not keyword:
            continue
        if " " in keyword:
            if keyword in text:
                return True
            continue
        if keyword in tokens:
            return True
        for token in tokens:
            if _lev(token, keyword, limit=max_dist) <= max_dist:
                return True
    return False


HOURS_KEYWORDS = {
    "hour",
    "hours",
    "opening",
    "opening hours",
    "opening time",
    "open hours",
    "open",
    "openin",
    "closing",
    "closing time",
    "closing hours",
    "clozing",
}

AVAILABILITY_KEYWORDS = {
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
    "any slots",
    "any availability",
    "what time u have",
    "what time you have",
    "book time",
    "any time",
    "anytime",
    "any time works",
    "anytime works",
    "any time tomorrow",
    "any time ok",
    "today",
    "tomorrow",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "thur",
    "wednsday",
    "thurzday",
    "friday",
    "saturday",
    "saturdy",
}

ADDRESS_KEYWORDS = {
    "address",
    "addres",
    "where",
    "postcode",
    "post code",
    "located",
    "location",
    "directions",
    "direcsion",
    "find",
}

PRICE_KEYWORDS = {
    "price",
    "prices",
    "prize",
    "prise",
    "cost",
    "how much",
    "fee",
    "fees",
    "charges",
    "pricing",
}

BOOKING_KEYWORDS = {
    "book",
    "booking",
    "appointment",
    "apointment",
    "appoinment",
    "schedule",
    "reserve",
    "checkup",
    "check-up",
    "see the dentist",
    "visit",
    "buk",
    "buking",
    "buk appointment",
}

GOODBYE_KEYWORDS = {
    "bye",
    "bye bye",
    "bye-bye",
    "goodbye",
    "that's all",
    "thats all",
    "that is all",
    "that's it",
    "thats it",
    "that is it",
    "nothing else",
    "no more",
    "finish",
    "we're good",
    "were good",
    "no thanks",
    "no thank you",
}

AFFIRM_KEYWORDS = {
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


def classify(speech: Optional[str]) -> Optional[str]:
    if not speech:
        return None

    text = _normalize(speech)
    if not text:
        return None

    if _any_fuzzy(text, BOOKING_KEYWORDS, max_dist=2):
        return "booking"
    if _any_fuzzy(text, HOURS_KEYWORDS, max_dist=1):
        return "hours"
    if _any_fuzzy(text, AVAILABILITY_KEYWORDS, max_dist=2):
        return "availability"
    if _any_fuzzy(text, ADDRESS_KEYWORDS, max_dist=2):
        return "address"
    if _any_fuzzy(text, PRICE_KEYWORDS, max_dist=2):
        return "prices"
    if _any_fuzzy(text, GOODBYE_KEYWORDS, max_dist=2):
        return "goodbye"
    if _any_fuzzy(text, AFFIRM_KEYWORDS, max_dist=1):
        return "affirm"
    return None


def parse_intent(speech: Optional[str]) -> Optional[str]:
    return classify(speech)


_APPT_KEYWORDS = {
    "check-up": "Check-up",
    "check up": "Check-up",
    "checkup": "Check-up",
    "chekup": "Check-up",
    "regular check": "Check-up",
    "hygiene": "Hygiene",
    "hygeine": "Hygiene",
    "clean": "Hygiene",
    "teeth clean": "Hygiene",
    "scale": "Hygiene",
    "whitening": "Whitening",
    "white ning": "Whitening",
    "white": "Whitening",
    "filling": "Filling",
    "fillin": "Filling",
    "tooth fill": "Filling",
    "emergency": "Emergency",
    "urgent": "Emergency",
}


def extract_appt_type(text: str) -> Optional[str]:
    lowered = _normalize(text)
    if not lowered:
        return None

    tokens = lowered.split()
    for raw, canonical in _APPT_KEYWORDS.items():
        target = _normalize(raw)
        if not target:
            continue
        if " " in target:
            if target in lowered:
                return canonical
        elif target in tokens:
            return canonical
    return None


__all__ = ["classify", "parse_intent", "extract_appt_type"]
