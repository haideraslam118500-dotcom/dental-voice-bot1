import xml.etree.ElementTree as ET

from main import create_gather_twiml, create_goodbye_twiml

VOICE = "Polly.Amy"
LANGUAGE = "en-GB"


def _parse_gather(xml: str) -> ET.Element:
    root = ET.fromstring(xml)
    gather = root.find("Gather")
    assert gather is not None, "Expected Gather element"
    return gather


def test_gather_is_speech_only_and_barge_in():
    xml = create_gather_twiml(
        "Hello there",
        action="/gather-intent",
        voice=VOICE,
        language=LANGUAGE,
    )
    gather = _parse_gather(xml)
    assert gather.attrib["input"] == "speech"
    assert gather.attrib["action"] == "/gather-intent"
    assert gather.attrib["method"] == "POST"
    assert gather.attrib.get("timeout") in {"5", "5.0"}
    assert gather.attrib.get("speechTimeout") == "auto"
    assert gather.attrib["language"] == LANGUAGE
    assert gather.attrib.get("bargeIn") in {"true", "True"}
    assert "numDigits" not in gather.attrib
    say = gather.find("Say")
    assert say is not None
    assert (say.text or "").strip() == "Hello there"


def test_gather_hints_are_optional():
    xml = create_gather_twiml(
        "Prompt",
        action="/gather-intent",
        voice=VOICE,
        language=LANGUAGE,
        hints="hours,prices",
    )
    gather = _parse_gather(xml)
    assert gather.attrib.get("hints") == "hours,prices"


def test_goodbye_twiml_includes_hangup():
    xml = create_goodbye_twiml(
        "Bye for now",
        voice=VOICE,
        language=LANGUAGE,
    )
    root = ET.fromstring(xml)
    assert root.find("Say") is not None
    assert root.find("Hangup") is not None
