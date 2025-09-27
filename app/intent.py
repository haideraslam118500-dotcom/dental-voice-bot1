from __future__ import annotations

import re
from typing import Iterable, Optional

from app.nlp import infer_service, normalise_text, detect_service


def _normalize(text: str) -> str:
    # Use shared normalisation so slot extraction and intent logic align.
    text = normalise_text(text)
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
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

QUOTE_KEYWORDS = {
    "quote",
    "how much",
    "price up",
    "rough price",
}

BOOKING_KEYWORDS = {
    "book",
    "booking",
    "appointment",
    "apointment",
    "appoinment",
    "schedule",
    "make booking",
    "slot",
    "slots",
    "slot in",
    "get me in",
    "can you fit me in",
    "reserve",
    "visit",
    "buk",
    "buking",
    "buk appointment",
}

GARAGE_INTENT_KEYWORDS: dict[str, set[str]] = {
    "mot_info": {"mot", "m o t"},
    "service_info": {"service", "servicing", "full service", "interim service"},
    "tyre_info": {"tyre", "tyres", "tire", "tires", "puncture", "wheel"},
    "diagnostics_info": {"diagnostic", "diagnostics", "engine light", "fault code", "obd"},
    "oil_info": {"oil change", "oil and filter", "oil & filter"},
    "brake_info": {"brake", "brakes", "pads", "discs"},
    "recovery": {"breakdown", "towing", "tow truck", "recovery"},
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
    "that s all",
    "that s it",
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

    goodbye_intent = _any_fuzzy(text, GOODBYE_KEYWORDS, max_dist=1)
    if goodbye_intent:
        return "goodbye"

    price_intent = _any_fuzzy(text, PRICE_KEYWORDS, max_dist=1)
    quote_intent = _any_fuzzy(text, QUOTE_KEYWORDS, max_dist=1)
    booking_intent = _any_fuzzy(text, BOOKING_KEYWORDS, max_dist=1)
    availability_intent = _any_fuzzy(text, AVAILABILITY_KEYWORDS, max_dist=2)
    address_intent = _any_fuzzy(text, ADDRESS_KEYWORDS, max_dist=2)
    hours_intent = _any_fuzzy(text, HOURS_KEYWORDS, max_dist=1)
    affirm_intent = _any_fuzzy(text, AFFIRM_KEYWORDS, max_dist=1)
    service = infer_service(speech)
    explicit_booking = any(
        keyword in text
        for keyword in ("book", "booking", "appointment", "schedule", "reserve", "make booking")
    )

    garage_hint = any(_any_fuzzy(text, keywords, max_dist=1) for keywords in GARAGE_INTENT_KEYWORDS.values())

    if quote_intent and not booking_intent:
        if not garage_hint:
            return "prices"
        return "quote"
    if price_intent and not booking_intent:
        return "prices"
    if booking_intent and not availability_intent:
        return "booking"
    if booking_intent and availability_intent and (explicit_booking or service):
        return "booking"
    if address_intent:
        return "address"
    if availability_intent:
        return "availability"
    if hours_intent:
        return "hours"
    for intent_name, keywords in GARAGE_INTENT_KEYWORDS.items():
        if _any_fuzzy(text, keywords, max_dist=1):
            return intent_name
    if price_intent:
        return "prices"
    if affirm_intent:
        return "affirm"
    if service:
        return "booking"
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
    "extraction": "Extraction",
    "extract": "Extraction",
    "tooth extraction": "Extraction",
    "tooth removal": "Extraction",
    "pull a tooth": "Extraction",
    "pull my tooth": "Extraction",
    "remove a tooth": "Extraction",
}


def extract_appt_type(text: str) -> Optional[str]:
    lowered = _normalize(text)
    if not lowered:
        return None

    service = infer_service(text)
    if service:
        mapping = {
            "checkup": "Check-up",
            "hygiene": "Hygiene",
            "whitening": "Whitening",
            "extraction": "Extraction",
        }
        mapped = mapping.get(service)
        if mapped:
            return mapped

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


def classify_with_slots(text: Optional[str]) -> tuple[Optional[str], dict[str, str]]:
    """Return the recognised intent along with any slots (e.g. inferred service)."""

    intent = classify(text)
    slots: dict[str, str] = {}
    service = detect_service(text)
    if service:
        slots["service"] = service
    return intent, slots


__all__ = ["classify", "parse_intent", "extract_appt_type", "classify_with_slots"]
