import xml.etree.ElementTree as ET

from main import MAX_SPEECH_CHARS, create_gather_twiml, create_goodbye_twiml

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


def test_gather_splits_long_prompt_into_multiple_chunks():
    long_text = (
        "We have appointments available next Tuesday at nine thirty, ten thirty, and twelve fifteen, "
        "as well as Wednesday at nine or eleven if those suit you."
    )
    xml = create_gather_twiml(
        long_text,
        action="/gather-intent",
        voice=VOICE,
        language=LANGUAGE,
    )
    gather = _parse_gather(xml)
    says = gather.findall("Say")
    assert len(says) >= 2
    lengths = [len((say.text or "").strip()) for say in says if (say.text or "").strip()]
    assert all(length <= MAX_SPEECH_CHARS for length in lengths)
    combined = " ".join((say.text or "").strip() for say in says)
    assert "appointments available next Tuesday" in combined
    assert "Wednesday at nine" in combined
