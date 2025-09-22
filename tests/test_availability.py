from datetime import date

import pandas as pd

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


def test_time_normalisation():
    from app import nlp

    assert nlp.normalize_time("4:00 p.m.") == "16:00"
    assert nlp.normalize_time("4 pm") == "16:00"
    assert nlp.normalize_time("10") == "10:00"


def test_list_available_sorted(monkeypatch):
    from app import schedule

    data = pd.DataFrame(
        [
            {
                "date": "2025-09-24",
                "weekday": "Wednesday",
                "start_time": "16:00",
                "end_time": "16:30",
                "status": "Available",
                "patient_name": "",
                "appointment_type": "",
                "notes": "",
            },
            {
                "date": "2025-09-24",
                "weekday": "Wednesday",
                "start_time": "09:00",
                "end_time": "09:30",
                "status": "Available",
                "patient_name": "",
                "appointment_type": "",
                "notes": "",
            },
            {
                "date": "2025-09-24",
                "weekday": "Wednesday",
                "start_time": "16:30",
                "end_time": "17:00",
                "status": "Available",
                "patient_name": "",
                "appointment_type": "",
                "notes": "",
            },
            {
                "date": "2025-09-24",
                "weekday": "Wednesday",
                "start_time": "11:00",
                "end_time": "11:30",
                "status": "Booked",
                "patient_name": "",  # not available
                "appointment_type": "",
                "notes": "",
            },
        ]
    )

    monkeypatch.setattr(schedule, "load_schedule", lambda: data.copy())

    avail = schedule.list_available(date="2025-09-24")
    times = [slot["start_time"] for slot in avail]
    assert times == ["09:00", "16:00", "16:30"]
