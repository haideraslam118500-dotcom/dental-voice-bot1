from app.intent import parse_intent

def test_speech_keywords_match():
    assert parse_intent("Can I book a visit?") == "booking"
    assert parse_intent("What's your address?") == "address"
    assert parse_intent("How much is a checkup?") == "prices"
    assert parse_intent("What time are you open?") == "hours"


def test_goodbye_detection():
    assert parse_intent("No thanks, that's all") == "goodbye"
    assert parse_intent("bye bye") == "goodbye"


def test_affirm_detection():
    assert parse_intent("Yes please") == "affirm"


def test_unknown_returns_none():
    assert parse_intent("I want to talk about something else") is None
