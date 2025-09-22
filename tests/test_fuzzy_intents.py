from app.intent import classify


def test_fuzzy_availability():
    assert classify("what availabilty you have thurzday") == "availability"
    assert classify("any time tomorrow ok") == "availability"


def test_fuzzy_booking():
    assert classify("i want buk apointment") == "booking"
    assert classify("buking please") == "booking"


def test_goodbye_variants():
    assert classify("that's it") == "goodbye"
    assert classify("no more") == "goodbye"
