from __future__ import annotations

from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_SCHEDULE_FILE = DATA_DIR / "schedule.csv"
SCHEDULE_FILE = DEFAULT_SCHEDULE_FILE  # Backwards compatibility for tests
BOOKINGS_FILE = DATA_DIR / "bookings.csv"

APPT_TYPES = ["Check-up", "Hygiene", "Whitening", "Extraction", "Filling", "Emergency"]


def schedule_csv_for_profile(profile: str | None) -> Path:
    desired = (profile or "").strip().lower()
    if desired:
        candidate = DATA_DIR / f"schedule_{desired}.csv"
        if candidate.exists():
            return candidate
    return DEFAULT_SCHEDULE_FILE


def load_schedule(profile: str | None = None) -> pd.DataFrame:
    schedule_file = schedule_csv_for_profile(profile)
    if not schedule_file.exists():
        return pd.DataFrame()
    df = pd.read_csv(schedule_file, dtype=str)
    expected = [
        "date",
        "weekday",
        "start_time",
        "end_time",
        "status",
        "patient_name",
        "appointment_type",
        "notes",
    ]
    for col in expected:
        if col not in df.columns:
            df[col] = ""
    return df[expected]


def save_schedule(df: pd.DataFrame, profile: str | None = None) -> None:
    schedule_file = schedule_csv_for_profile(profile)
    schedule_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(schedule_file, index=False)


def list_available(date: str | None = None, limit: int = 6, profile: str | None = None):
    try:
        df = load_schedule(profile=profile)
    except TypeError:  # Backwards compatibility for monkeypatched tests
        df = load_schedule()
    if df.empty:
        return []
    avail = df[df["status"] == "Available"].copy()
    if date:
        avail = avail[avail["date"] == date]
    try:
        avail["__t"] = pd.to_datetime(avail["start_time"], format="%H:%M")
        avail = avail.sort_values("__t").drop(columns=["__t"])
    except Exception:
        pass
    return avail.head(limit).to_dict(orient="records")


def find_next_available(profile: str | None = None) -> dict | None:
    try:
        df = load_schedule(profile=profile)
    except TypeError:
        df = load_schedule()
    if df.empty:
        return None
    avail = df[df["status"] == "Available"]
    if avail.empty:
        return None
    return avail.iloc[0].to_dict()


def reserve_slot(
    date: str,
    start_time: str,
    name: str,
    appt_type: str,
    profile: str | None = None,
) -> bool:
    try:
        df = load_schedule(profile=profile)
    except TypeError:
        df = load_schedule()
    if df.empty:
        return False
    mask = (df["date"] == date) & (df["start_time"] == start_time)
    if not mask.any():
        return False
    if (df.loc[mask, "status"].iloc[0] or "").strip() != "Available":
        return False
    df.loc[mask, "status"] = "Booked"
    df.loc[mask, "patient_name"] = name
    df.loc[mask, "appointment_type"] = appt_type
    try:
        save_schedule(df, profile=profile)
    except TypeError:
        save_schedule(df)
    if not BOOKINGS_FILE.exists():
        BOOKINGS_FILE.write_text("timestamp,call_sid,caller_name,requested_time,intent\n", encoding="utf-8")
    with BOOKINGS_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"{pd.Timestamp.now().isoformat()},{''},{name},{date} {start_time},book\n")
    return True

