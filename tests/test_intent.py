from app.intent import parse_intent


def test_digits_map_to_intent():
    assert parse_intent(None, "1") == "hours"
    assert parse_intent(None, "4") == "booking"


def test_speech_keywords_match():
    assert parse_intent("Can I book a visit?", None) == "booking"
    assert parse_intent("What's your address?", None) == "address"


def test_unknown_returns_none():
    assert parse_intent("I want to chat", None) is None
