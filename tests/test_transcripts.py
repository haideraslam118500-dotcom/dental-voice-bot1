def test_transcript_add_and_save(tmp_path, monkeypatch):
    from app import persistence

    transcripts_dir = tmp_path / "transcripts"
    data_dir = tmp_path / "data"

    monkeypatch.setattr(persistence, "TRANSCRIPTS_DIR", transcripts_dir)
    monkeypatch.setattr(persistence, "DATA_DIR", data_dir)
    monkeypatch.setattr(persistence, "BOOKINGS_CSV", data_dir / "bookings.csv")
    monkeypatch.setattr(persistence, "CALLS_JSONL", data_dir / "calls.jsonl")
    monkeypatch.setattr(persistence, "_TRANSCRIPTS", {})

    persistence.ensure_storage()

    call_sid = "TEST123"
    persistence.transcript_init(call_sid)
    persistence.transcript_add(call_sid, "Agent", "Hello there")
    persistence.transcript_add(call_sid, "Caller", "I need an appointment")

    lines = persistence.transcript_pop(call_sid)
    assert lines == ["[Agent] Hello there", "[Caller] I need an appointment"]

    transcript_path = persistence.save_transcript(call_sid, lines)

    assert transcript_path.is_file()
    content = transcript_path.read_text(encoding="utf-8")
    assert "[Agent] Hello there" in content
    assert "[Caller] I need an appointment" in content
    assert content.strip() != ""
