from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    call_sid TEXT PRIMARY KEY,
    caller TEXT,
    intent TEXT,
    requested_time TEXT,
    finished_at TEXT
);
"""


def ensure_schema(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(_SCHEMA)
        conn.commit()


def persist_call_summary(
    db_path: Path,
    call_sid: str,
    caller: Optional[str],
    intent: Optional[str],
    requested_time: Optional[str],
) -> None:
    finished_at = datetime.now(tz=timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO calls(call_sid, caller, intent, requested_time, finished_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (call_sid, caller, intent, requested_time, finished_at),
        )
        conn.commit()
    logger.info("Persisted call summary", extra={
        "call_sid": call_sid,
        "caller": caller,
        "intent": intent,
        "requested_time": requested_time,
    })


__all__ = ["ensure_schema", "persist_call_summary"]
