import asyncio
from datetime import date
from xml.etree import ElementTree as ET

import main
from main import CALLS, gather_booking_route, gather_intent_route, voice_webhook


class DummyRequest:
    def __init__(self, form_data: dict[str, str]):
        self._form_data = form_data

    async def form(self) -> dict[str, str]:
        return self._form_data


def _gather_text(xml: str) -> str:
    root = ET.fromstring(xml)
    gather = root.find("Gather")
    assert gather is not None, "Expected Gather element"
    say = gather.find("Say")
    assert say is not None, "Expected Say within Gather"
    return (say.text or "").strip()


def _call_route(route, data: dict[str, str]):
    response = asyncio.run(route(DummyRequest(data)))
    return response


def test_booking_flow_follows_type_date_time_name(monkeypatch):
    CALLS.clear()
    call_sid = "TESTBOOK1"

    # Freeze today for deterministic date parsing
    monkeypatch.setattr(main.nlp, "today_date", lambda: date(2025, 9, 22))

    slots = [
        {"date": "2025-09-23", "start_time": "10:00", "end_time": "10:30", "status": "Available"},
        {"date": "2025-09-23", "start_time": "10:30", "end_time": "11:00", "status": "Available"},
    ]

    def fake_list_available(*, date: str | None = None, limit: int = 6):
        if date:
            return [slot for slot in slots if slot["date"] == date][:limit]
        return slots[:limit]

    monkeypatch.setattr(main.schedule, "list_available", lambda date=None, limit=6: fake_list_available(date=date, limit=limit))
    monkeypatch.setattr(main.schedule, "find_next_available", lambda: slots[0])
    monkeypatch.setattr(main.schedule, "reserve_slot", lambda d, t, name, appt: True)

    response = _call_route(voice_webhook, {"CallSid": call_sid})
    assert response.status_code == 200

    response = _call_route(
        gather_intent_route,
        {"CallSid": call_sid, "SpeechResult": "I'd like to book an appointment"},
    )
    assert response.status_code == 200
    prompt = _gather_text(response.body.decode()).lower()
    assert "what type" in prompt

    response = _call_route(
        gather_booking_route,
        {"CallSid": call_sid, "SpeechResult": "check-up"},
    )
    assert response.status_code == 200
    prompt = _gather_text(response.body.decode()).lower()
    assert "what day" in prompt

    response = _call_route(
        gather_booking_route,
        {"CallSid": call_sid, "SpeechResult": "Tomorrow"},
    )
    assert response.status_code == 200
    prompt = _gather_text(response.body.decode()).lower()
    assert "2025-09-23" in prompt
    assert "10:00" in prompt

    response = _call_route(
        gather_booking_route,
        {"CallSid": call_sid, "SpeechResult": "10am"},
    )
    assert response.status_code == 200
    prompt = _gather_text(response.body.decode()).lower()
    assert "name" in prompt

    response = _call_route(
        gather_booking_route,
        {"CallSid": call_sid, "SpeechResult": "Jane"},
    )
    assert response.status_code == 200
    prompt = _gather_text(response.body.decode()).lower()
    assert "shall i book you in" in prompt
    CALLS.pop(call_sid, None)
