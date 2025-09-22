from datetime import date

from app import nlp, schedule


def test_parse_date_phrase_weekday(monkeypatch):
    monkeypatch.setattr(nlp, "today_date", lambda: date(2025, 9, 22))  # Monday
    assert nlp.parse_date_phrase("tomorrow") == "2025-09-23"
    assert nlp.parse_date_phrase("Wednesday") == "2025-09-24"


def test_schedule_list_and_reserve(tmp_path, monkeypatch):
    import shutil

    src = schedule.SCHEDULE_FILE
    dst = tmp_path / "schedule.csv"
    shutil.copy(src, dst)
    monkeypatch.setattr(schedule, "SCHEDULE_FILE", dst)
    monkeypatch.setattr(schedule, "BOOKINGS_FILE", tmp_path / "bookings.csv")

    avail = schedule.list_available(limit=2)
    assert isinstance(avail, list)

    if avail:
        s0 = avail[0]
        ok = schedule.reserve_slot(s0["date"], s0["start_time"], "TestUser", "Check-up")
        assert ok
