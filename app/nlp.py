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

