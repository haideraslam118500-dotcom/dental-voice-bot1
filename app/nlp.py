from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from datetime import date as _date
from typing import Optional, Sequence


def today_date() -> _date:
    """Helper used by tests; returns the current local date."""
    return _date.today()


def _ordinal(n: int) -> str:
    """Turn 1 into 1st, 2 into 2nd, etc."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def human_day_phrase(yyyy_mm_dd: str) -> str:
    """Convert YYYY-MM-DD strings into natural, speech-friendly phrases."""
    try:
        target = datetime.strptime(yyyy_mm_dd, "%Y-%m-%d").date()
    except Exception:
        return yyyy_mm_dd

    today = today_date()
    if target == today:
        return "today"
    if target == today + timedelta(days=1):
        return "tomorrow"

    delta = target - today
    if 0 < delta.days <= 7:
        return f"this {target.strftime('%A')}"

    return f"{target.strftime('%A')} the {_ordinal(target.day)}"


WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}


def parse_date_phrase(text: str) -> str | None:
    if not text:
        return None
    lowered = text.lower().strip()
    base = today_date()

    if "today" in lowered:
        return base.strftime("%Y-%m-%d")
    if "tomorrow" in lowered:
        return (base + timedelta(days=1)).strftime("%Y-%m-%d")

    for name, idx in WEEKDAYS.items():
        if re.search(rf"\b{name[:3]}\w*\b", lowered):
            delta = (idx - base.weekday()) % 7
            if delta == 0:
                delta = 7
            return (base + timedelta(days=delta)).strftime("%Y-%m-%d")
    return None


def normalize_time(text: str) -> str | None:
    if not text:
        return None
    lowered = text.lower().strip()
    # tolerate punctuation variants like “4:00 p.m.”
    lowered = lowered.replace(".", "")

    if "half past" in lowered:
        m2 = re.search(r"half past (\d{1,2})", lowered)
        if m2:
            hour = int(m2.group(1))
            if 0 <= hour < 24:
                return f"{hour:02d}:30"

    if "quarter past" in lowered:
        m2 = re.search(r"quarter past (\d{1,2})", lowered)
        if m2:
            hour = int(m2.group(1))
            if 0 <= hour < 24:
                return f"{hour:02d}:15"

    if "quarter to" in lowered:
        m2 = re.search(r"quarter to (\d{1,2})", lowered)
        if m2:
            hour = int(m2.group(1)) - 1
            if hour < 0:
                hour = 23
            return f"{hour:02d}:45"

    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lowered)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = (match.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return f"{hour:02d}:{minute:02d}"


def hhmm_to_12h(hhmm: str) -> str:
    """Convert a 24-hour HH:MM string into a human friendly 12-hour form."""

    try:
        hour_str, minute_str = hhmm.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
    except Exception:
        return hhmm

    suffix = "am" if hour < 12 else "pm"
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12

    if minute == 0:
        return f"{display_hour}{suffix}"
    return f"{display_hour}:{minute:02d}{suffix}"


def maybe_prefix_with_filler(
    text: str,
    fillers: Sequence[str],
    chance: float = 0.5,
) -> list[tuple[str, str]]:
    """Optionally prepend a short filler + pause to avoid silence."""

    import random

    parts: list[tuple[str, str]] = []
    if fillers and chance > 0 and random.random() < chance:
        filler = random.choice(list(fillers)).strip()
        if text:
            combined = f"{filler} {text}" if filler else text
        else:
            combined = filler
        parts.append(("say", combined.strip()))
        return parts
    parts.append(("say", text))
    return parts


def fuzzy_pick_time(user_text: str, available_hhmm: list[str]) -> str | None:
    """Map fuzzy user input to an available HH:MM slot."""

    if not user_text:
        return None

    avail_list = list(available_hhmm or [])
    if not avail_list:
        return None
    avail_set = set(avail_list)

    lowered = (user_text or "").lower()
    ampm_check = lowered.replace(".", "")
    has_ampm = bool(re.search(r"\d\s*(?:a|p)\s*m", ampm_check))

    norm = normalize_time(user_text)
    if norm and norm in avail_set:
        return norm

    # strip am/pm markers that may block digit matching
    sanitized = ampm_check
    sanitized = re.sub(r"(?<=\d)\s*(?:a|p)\s*m", "", sanitized)
    sanitized = re.sub(r"(?<=\d)(?=[a-z])", " ", sanitized)
    sanitized = re.sub(r"(?<=[a-z])(?=\d)", " ", sanitized)

    def try_candidates(raw_hour: int, minute: str | None, *, allow_half_hour: bool) -> str | None:
        if raw_hour < 0:
            return None
        minutes = minute
        if minutes is not None:
            try:
                minutes_int = int(minutes)
            except ValueError:
                return None
            minutes = f"{minutes_int:02d}"
        base_minutes = minutes or "00"
        candidates = []
        for cand_hour in (raw_hour % 24, (raw_hour % 12) + 12):
            if 0 <= cand_hour < 24 and cand_hour not in candidates:
                candidates.append(cand_hour)
        for cand_hour in candidates:
            candidate = f"{cand_hour:02d}:{base_minutes}"
            if candidate in avail_set:
                return candidate
        if minutes is None and allow_half_hour:
            for cand_hour in candidates:
                candidate = f"{cand_hour:02d}:30"
                if candidate in avail_set:
                    return candidate
        return None

    # Pattern like "4:30" or "4 : 30"
    colon_matches = list(re.finditer(r"(\d{1,2})\s*[:]\s*(\d{1,2})", sanitized))
    if colon_matches:
        h = int(colon_matches[-1].group(1))
        m = colon_matches[-1].group(2)
        picked = try_candidates(h, m, allow_half_hour=False)
        if picked:
            return picked

    # Pattern like "4 30"
    space_matches = list(re.finditer(r"(\d{1,2})\s+(\d{2})\b", sanitized))
    if space_matches:
        h = int(space_matches[-1].group(1))
        m = space_matches[-1].group(2)
        picked = try_candidates(h, m, allow_half_hour=False)
        if picked:
            return picked

    # Contiguous digits such as "430" or "1230"
    for match in reversed(list(re.finditer(r"\b(\d{3,4})\b", sanitized))):
        digits = match.group(1)
        h = int(digits[:-2])
        m = digits[-2:]
        picked = try_candidates(h, m, allow_half_hour=False)
        if picked:
            return picked

    # Finally, look at standalone hour digits (take the last one mentioned)
    for match in reversed(list(re.finditer(r"\b(\d{1,2})\b", sanitized))):
        h = int(match.group(1))
        picked = try_candidates(h, None, allow_half_hour=not has_ampm)
        if picked:
            return picked

    return None

_SERVICE_SYNONYMS = {
    "checkup": [
        "check up",
        "check-up",
        "checkup",
        "exam",
        "examination",
        "see the dentist",
        "quick look",
    ],
    "hygiene": [
        "hygiene",
        "clean",
        "cleaning",
        "scale",
        "scale and polish",
        "polish",
        "deep clean",
    ],
    "whitening": [
        "whiten",
        "whitening",
        "teeth whitening",
        "bleaching",
    ],
    "extraction": [
        "extract",
        "extraction",
        "tooth out",
        "pull a tooth",
        "tooth removal",
        "remove a tooth",
        "pull my tooth",
    ],
}


def infer_service(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    for canonical, variants in _SERVICE_SYNONYMS.items():
        for variant in variants:
            if variant in lowered:
                return canonical
    return None


_HOUR12 = re.compile(
    r"\b(?P<h>\d{1,2})(:(?P<m>\d{2}))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?|am|pm)?\b"
)


def parse_time_like(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    if not lowered:
        return None
    half_match = re.search(r"\bhalf\s+past\s+(\d{1,2})\b", lowered)
    if half_match:
        hour = int(half_match.group(1)) % 12
        # assume afternoon preference; downstream logic may adjust context
        return f"{hour + 12:02d}:30"

    match = _HOUR12.search(lowered)
    if not match:
        return None

    hour = int(match.group("h"))
    minute = match.group("m") or "00"
    ampm = match.group("ampm")
    if ampm:
        ampm_clean = ampm.replace(".", "")
        if ampm_clean == "pm" and hour < 12:
            hour += 12
        if ampm_clean == "am" and hour == 12:
            hour = 0
    hour %= 24
    return f"{hour:02d}:{int(minute):02d}"
