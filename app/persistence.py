from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

TRANSCRIPTS_DIR = Path("transcripts")
DATA_DIR = Path("data")
BOOKINGS_CSV = DATA_DIR / "bookings.csv"
CALLS_JSONL = DATA_DIR / "calls.jsonl"


def ensure_storage() -> None:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _next_transcript_index() -> int:
    ensure_storage()
    max_index = 0
    prefix = "AI Incoming Call "
    for path in TRANSCRIPTS_DIR.glob("AI Incoming Call *.txt"):
        stem = path.stem
        if not stem.startswith(prefix):
            continue
        remainder = stem[len(prefix) :]
        parts = remainder.split(" ")
        if not parts:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            continue
        if index > max_index:
            max_index = index
    return max_index + 1


def save_transcript(call_sid: str, transcript: Iterable[str]) -> Path:
    ensure_storage()
    now = datetime.now()
    index = _next_transcript_index()
    filename = f"AI Incoming Call {index:04d} {now:%H-%M} {now:%d-%m-%y}.txt"
    path = TRANSCRIPTS_DIR / filename
    lines: List[str] = [entry.rstrip() for entry in transcript]
    with path.open("w", encoding="utf-8") as handle:
        for entry in lines:
            handle.write(entry + "\n")
    logger.info("Saved transcript", extra={"call_sid": call_sid, "path": str(path)})
    return path


def append_booking(call_sid: str, caller_name: Optional[str], requested_time: Optional[str]) -> None:
    if not requested_time:
        return
    ensure_storage()
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    is_new = not BOOKINGS_CSV.exists()
    with BOOKINGS_CSV.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(["timestamp", "call_sid", "caller_name", "requested_time", "intent"])
        writer.writerow([timestamp, call_sid, caller_name or "", requested_time.strip(), "book"])
    logger.info(
        "Logged booking request",
        extra={"call_sid": call_sid, "requested_time": requested_time, "caller_name": caller_name},
    )


def append_call_record(summary: dict) -> None:
    ensure_storage()
    summary = dict(summary)
    summary.setdefault("finished_at", datetime.now(tz=timezone.utc).isoformat())
    with CALLS_JSONL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False) + "\n")
    logger.info("Logged call summary", extra={"call_sid": summary.get("call_sid")})


__all__ = ["ensure_storage", "save_transcript", "append_booking", "append_call_record"]
