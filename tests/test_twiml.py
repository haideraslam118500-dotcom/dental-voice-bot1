import xml.etree.ElementTree as ET

from app.twiml import (
    gather_first_name,
    gather_intent,
    respond_with_booking_confirmation,
    respond_with_information,
)


VOICE = "alice"
LANG = "en-GB"


def _get_gather(xml: str) -> ET.Element:
    root = ET.fromstring(xml)
    gather = root.find("Gather")
    assert gather is not None, "Expected a Gather element"
    return gather


def test_gather_first_name_uses_speech_only():
    twiml = gather_first_name(0, VOICE, LANG)
    gather = _get_gather(twiml)
    assert gather.attrib["input"] == "speech"
    assert gather.attrib["action"] == "/gather-intent"
    say = gather.find("Say")
    assert say is not None
    assert "first name" in (say.text or "")


def test_gather_intent_allows_dtmf():
    twiml = gather_intent("Sam", 1, VOICE, LANG)
    gather = _get_gather(twiml)
    assert gather.attrib["input"] == "speech dtmf"
    assert gather.attrib.get("numDigits") == "1"
    say = gather.find("Say")
    assert say is not None
    assert "press 1" in (say.text or "").lower()


def test_booking_confirmation_includes_name():
    twiml = respond_with_booking_confirmation("Monday at 2", VOICE, LANG, "Alex")
    root = ET.fromstring(twiml)
    say = root.find("Say")
    assert say is not None
    assert "Alex" in (say.text or "")
    assert "Monday at 2" in (say.text or "")


def test_information_response_hangs_up():
    twiml = respond_with_information("hours", VOICE, LANG, "Sam")
    root = ET.fromstring(twiml)
    assert root.find("Say") is not None
    assert root.find("Hangup") is not None
