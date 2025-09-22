from datetime import date

from app import nlp


def test_human_day_phrase_basic(monkeypatch):
    today = date(2025, 9, 22)
    monkeypatch.setattr(nlp, "today_date", lambda: today)

    assert nlp.human_day_phrase("2025-09-23").lower() == "tomorrow"
    assert nlp.human_day_phrase("2025-09-25").lower() == "this thursday"
    assert "thursday the" in nlp.human_day_phrase("2025-10-02").lower()
