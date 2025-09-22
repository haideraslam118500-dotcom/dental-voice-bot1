from app.intent import parse_intent


def test_digits_map_to_intent():
    assert parse_intent(None, "1") == "hours"
    assert parse_intent(None, "4") == "booking"


def test_speech_keywords_match():
    assert parse_intent("Can I book a visit?", None) == "booking"
    assert parse_intent("What's your address?", None) == "address"
    assert parse_intent("How much is a checkup?", None) == "prices"
    assert parse_intent("What time are you open?", None) == "hours"


def test_goodbye_detection():
    assert parse_intent("No thanks, that's all", None) == "goodbye"
    assert parse_intent("bye bye", None) == "goodbye"


def test_affirm_detection():
    assert parse_intent("Yes please", None) == "affirm"


def test_unknown_returns_none():
    assert parse_intent("I want to talk about something else", None) is None
