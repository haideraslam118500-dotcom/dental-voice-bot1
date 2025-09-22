from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Dict, Optional


@dataclass
class CallState:
    call_sid: str
    caller_name: Optional[str] = None
    intent: Optional[str] = None
    requested_time: Optional[str] = None
    name_attempts: int = 0
    intent_attempts: int = 0
    booking_attempts: int = 0


class CallStateStore:
    def __init__(self) -> None:
        self._states: Dict[str, CallState] = {}
        self._lock = Lock()

    def get_or_create(self, call_sid: str) -> CallState:
        with self._lock:
            state = self._states.get(call_sid)
            if state is None:
                state = CallState(call_sid=call_sid)
                self._states[call_sid] = state
            return state

    def get(self, call_sid: str) -> Optional[CallState]:
        with self._lock:
            return self._states.get(call_sid)

    def remove(self, call_sid: str) -> Optional[CallState]:
        with self._lock:
            return self._states.pop(call_sid, None)

    def clear(self) -> None:
        with self._lock:
            self._states.clear()


__all__ = ["CallState", "CallStateStore"]
