from app import schedule


def test_schedule_cycle(tmp_path, monkeypatch):
    import shutil

    data_file = tmp_path / "schedule.csv"
    shutil.copy("data/schedule.csv", data_file)
    monkeypatch.setattr(schedule, "SCHEDULE_FILE", data_file)
    monkeypatch.setattr(schedule, "BOOKINGS_FILE", tmp_path / "bookings.csv")

    df = schedule.load_schedule()
    assert not df.empty
    avail = schedule.list_available(limit=2)
    assert all(s["status"] == "Available" for s in avail)

    s0 = avail[0]
    ok = schedule.reserve_slot(s0["date"], s0["start_time"], "TestUser", "Check-up")
    assert ok
    df2 = schedule.load_schedule()
    assert (df2[df2["date"] == s0["date"]]["status"] == "Booked").any()
