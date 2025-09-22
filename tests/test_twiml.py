import random
import xml.etree.ElementTree as ET

from app import dialogue
from app.twiml import (
    gather_for_follow_up,
    gather_for_intent,
    gather_for_name,
    respond_with_goodbye,
)

VOICE = "alice"
LANG = "en-GB"


def _get_gather(xml: str) -> ET.Element:
    root = ET.fromstring(xml)
    gather = root.find("Gather")
    assert gather is not None, "Expected a Gather element"
    return gather


def test_gather_intent_allows_dtmf():
    twiml = gather_for_intent("Tell me how to help", VOICE, LANG)
    gather = _get_gather(twiml)
    assert gather.attrib["input"] == "speech dtmf"
    assert gather.attrib.get("numDigits") == "1"
    assert gather.attrib["action"] == "/gather-intent"


def test_hours_prompt_contains_hours_line():
    random.seed(1)
    prompt = dialogue.compose_info_prompt("hours")
    twiml = gather_for_follow_up(prompt, VOICE, LANG)
    say = _get_gather(twiml).find("Say")
    assert say is not None
    assert dialogue.HOURS_LINE in (say.text or "")


def test_address_prompt_contains_address_line():
    random.seed(2)
    prompt = dialogue.compose_info_prompt("address")
    twiml = gather_for_follow_up(prompt, VOICE, LANG)
    say = _get_gather(twiml).find("Say")
    assert say is not None
    assert dialogue.ADDRESS_LINE in (say.text or "")


def test_prices_prompt_contains_prices_line():
    random.seed(3)
    prompt = dialogue.compose_info_prompt("prices")
    twiml = gather_for_follow_up(prompt, VOICE, LANG)
    say = _get_gather(twiml).find("Say")
    assert say is not None
    assert dialogue.PRICES_LINE in (say.text or "")


def test_booking_name_prompt_mentions_name():
    random.seed(4)
    prompt = dialogue.compose_booking_name_prompt()
    twiml = gather_for_name(prompt, VOICE, LANG)
    gather = _get_gather(twiml)
    assert gather.attrib["input"] == "speech"
    say = gather.find("Say")
    assert say is not None
    assert "name" in (say.text or "").lower()


def test_booking_confirmation_mentions_time_and_name():
    random.seed(5)
    prompt = dialogue.compose_booking_confirmation("Sam", "Monday at 2")
    twiml = gather_for_follow_up(prompt, VOICE, LANG)
    say = _get_gather(twiml).find("Say")
    assert say is not None
    text = say.text or ""
    assert "Monday at 2" in text
    assert "Sam" in text


def test_goodbye_twiml_hangs_up():
    random.seed(6)
    message = dialogue.pick_goodbye()
    twiml = respond_with_goodbye(message, VOICE, LANG)
    root = ET.fromstring(twiml)
    assert root.find("Say") is not None
    assert root.find("Hangup") is not None
