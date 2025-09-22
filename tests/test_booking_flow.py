import asyncio
from xml.etree import ElementTree as ET

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


def test_booking_flow_requests_time_before_name():
    CALLS.clear()
    call_sid = "TESTBOOK1"

    response = _call_route(voice_webhook, {"CallSid": call_sid})
    assert response.status_code == 200

    response = _call_route(
        gather_intent_route,
        {"CallSid": call_sid, "SpeechResult": "I'd like to book an appointment"},
    )
    assert response.status_code == 200
    prompt = _gather_text(response.body.decode()).lower()
    assert "time" in prompt
    assert "name" not in prompt

    response = _call_route(
        gather_booking_route,
        {"CallSid": call_sid, "SpeechResult": "Tomorrow at 10am"},
    )
    assert response.status_code == 200
    prompt = _gather_text(response.body.decode()).lower()
    assert "name" in prompt
    CALLS.pop(call_sid, None)
