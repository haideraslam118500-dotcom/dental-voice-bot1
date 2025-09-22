from app import nlp


def test_hhmm_to_12h():
    assert nlp.hhmm_to_12h("09:00") == "9am"
    assert nlp.hhmm_to_12h("16:00").lower() == "4pm"
    assert nlp.hhmm_to_12h("16:30").lower() == "4:30pm"


def test_fuzzy_pick_time():
    avail = ["09:30", "11:00", "11:30", "12:00", "14:30", "16:30"]
    assert nlp.fuzzy_pick_time("4:30", avail) == "16:30"
    assert nlp.fuzzy_pick_time("430", avail) == "16:30"
    assert nlp.fuzzy_pick_time("4", avail) == "16:30"
    assert nlp.fuzzy_pick_time("4 pm", avail) is None
    assert nlp.fuzzy_pick_time("tomorrow at 4", avail) == "16:30"
