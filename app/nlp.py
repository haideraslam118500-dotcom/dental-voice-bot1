from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta


def today_date() -> date:
    return datetime.now().date()


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

