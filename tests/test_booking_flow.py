import asyncio
from datetime import date
from itertools import cycle
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


def _first_say_text(xml: str) -> str:
    root = ET.fromstring(xml)
    say = root.find(".//Say")
    assert say is not None, "Expected Say element"
    return (say.text or "").strip()


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


def test_inline_type_prefill_skips_type_question(monkeypatch):
    CALLS.clear()
    call_sid = "TESTINLINE"

    monkeypatch.setattr(main.nlp, "today_date", lambda: date(2025, 9, 22))
    monkeypatch.setattr(main.schedule, "list_available", lambda date=None, limit=6: [])
    monkeypatch.setattr(main.schedule, "find_next_available", lambda: None)
    monkeypatch.setattr(main.schedule, "reserve_slot", lambda d, t, name, appt: True)

    response = _call_route(voice_webhook, {"CallSid": call_sid})
    assert response.status_code == 200

    phrase = "I want to book a hygiene appointment on Wednesday"
    response = _call_route(
        gather_intent_route,
        {"CallSid": call_sid, "SpeechResult": phrase},
    )
    assert response.status_code == 200
    prompt = _gather_text(response.body.decode())
    assert "Great, a Hygiene" in prompt
    assert "what type" not in prompt.lower()

    state = CALLS.get(call_sid)
    assert state is not None
    assert state.get("booking_appt_type") == "Hygiene"
    assert state.get("stage") == "booking_date"
    CALLS.pop(call_sid, None)


def test_booking_confirmation_prompts_anything_else_and_goodbye(monkeypatch):
    CALLS.clear()
    call_sid = "TESTCLOSE"

    monkeypatch.setattr(main.nlp, "today_date", lambda: date(2025, 9, 22))

    slots = [
        {"date": "2025-09-24", "start_time": "16:00", "end_time": "16:30", "status": "Available"},
        {"date": "2025-09-24", "start_time": "09:00", "end_time": "09:30", "status": "Available"},
        {"date": "2025-09-24", "start_time": "16:30", "end_time": "17:00", "status": "Available"},
    ]

    def fake_list_available(*, date: str | None = None, limit: int = 6):
        pool = [slot for slot in slots if not date or slot["date"] == date]
        return pool[:limit]

    monkeypatch.setattr(main.schedule, "list_available", lambda date=None, limit=6: fake_list_available(date=date, limit=limit))
    monkeypatch.setattr(main.schedule, "find_next_available", lambda: slots[0])
    monkeypatch.setattr(main.schedule, "reserve_slot", lambda d, t, name, appt: True)
    monkeypatch.setattr(main, "_goodbye_cycle", cycle(["Thanks for calling, goodbye."]))

    response = _call_route(voice_webhook, {"CallSid": call_sid})
    assert response.status_code == 200

    response = _call_route(
        gather_intent_route,
        {"CallSid": call_sid, "SpeechResult": "I'd like to book an appointment"},
    )
    assert response.status_code == 200

    response = _call_route(
        gather_booking_route,
        {"CallSid": call_sid, "SpeechResult": "Hygiene"},
    )
    prompt = _gather_text(response.body.decode())
    assert "what day" in prompt.lower()

    response = _call_route(
        gather_booking_route,
        {"CallSid": call_sid, "SpeechResult": "Wednesday"},
    )
    prompt = _gather_text(response.body.decode())
    assert "2025-09-24" in prompt
    assert "09:00" in prompt
    assert "16:30" in prompt

    response = _call_route(
        gather_booking_route,
        {"CallSid": call_sid, "SpeechResult": "4:00 p.m."},
    )
    prompt = _gather_text(response.body.decode())
    assert "name" in prompt.lower()

    response = _call_route(
        gather_booking_route,
        {"CallSid": call_sid, "SpeechResult": "Alice"},
    )
    prompt = _gather_text(response.body.decode())
    assert "shall i book you in" in prompt.lower()

    response = _call_route(
        gather_booking_route,
        {"CallSid": call_sid, "SpeechResult": "yes please"},
    )
    prompt = _gather_text(response.body.decode())
    assert "Is there anything else I can help you with?" in prompt

    response = _call_route(
        gather_intent_route,
        {"CallSid": call_sid, "SpeechResult": "No thanks"},
    )
    assert response.status_code == 200
    farewell = _first_say_text(response.body.decode())
    assert farewell == "Thanks for calling, goodbye."

    state = CALLS.get(call_sid)
    assert state is not None
    transcript_lines = state.get("transcript") or []
    assert any("Is there anything else I can help you with?" in line for line in transcript_lines)
    assert any("Thanks for calling, goodbye." in line for line in transcript_lines)
    CALLS.pop(call_sid, None)
