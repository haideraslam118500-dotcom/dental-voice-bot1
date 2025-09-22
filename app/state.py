from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List, Optional


@dataclass
class CallState:
    call_sid: str
    caller_name: Optional[str] = None
    intent: Optional[str] = None
    requested_time: Optional[str] = None
    transcript: List[str] = field(default_factory=list)
    awaiting: str = "intent"
    retries: Dict[str, int] = field(
        default_factory=lambda: {"intent": 0, "name": 0, "time": 0}
    )
    silence_count: int = 0
    completed: bool = False
    transcript_file: Optional[str] = None
    final_goodbye: Optional[str] = None
    metadata: Dict[str, Optional[str]] = field(default_factory=dict)
    has_greeted: bool = False
    prompted_after_greeting: bool = False

    def add_system_line(self, text: str) -> None:
        text = text.strip()
        if text:
            self.transcript.append(f"AI: {text}")

    def add_caller_line(self, text: str) -> None:
        text = text.strip()
        if text:
            self.transcript.append(f"Caller: {text}")

    def reset_retries(self, key: str) -> None:
        if key in self.retries:
            self.retries[key] = 0

    def bump_retry(self, key: str) -> int:
        if key not in self.retries:
            self.retries[key] = 0
        self.retries[key] += 1
        return self.retries[key]

    def reset_silence(self) -> None:
        self.silence_count = 0


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
