from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, List, Sequence

try:  # pragma: no cover - optional dependency
    import pandas as pd  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pd = None  # type: ignore[assignment]

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SCHEDULE_FILE = DATA_DIR / "schedule.csv"
BOOKINGS_FILE = DATA_DIR / "bookings.csv"

APPT_TYPES = ["Check-up", "Hygiene", "Whitening", "Filling", "Emergency"]

DEFAULT_COLUMNS: Sequence[str] = (
    "date",
    "weekday",
    "start_time",
    "end_time",
    "status",
    "patient_name",
    "appointment_type",
    "notes",
)


class Mask:
    __slots__ = ("_values",)

    def __init__(self, values: Iterable[bool]):
        self._values = [bool(v) for v in values]

    @property
    def values(self) -> List[bool]:
        return list(self._values)

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __and__(self, other: object) -> "Mask":
        if isinstance(other, Mask):
            other_values = other._values
        elif isinstance(other, Sequence):
            other_values = [bool(v) for v in other]
        else:  # pragma: no cover - defensive fallback
            raise TypeError("Unsupported mask type for logical and")
        if len(other_values) != len(self._values):
            raise ValueError("Mask length mismatch")
        return Mask(a and b for a, b in zip(self._values, other_values))

    def any(self) -> bool:
        return any(self._values)


class _SeriesILoc:
    __slots__ = ("_series",)

    def __init__(self, series: "Series") -> None:
        self._series = series

    def __getitem__(self, index: int):
        return self._series._values[index]


class Series:
    __slots__ = ("_df", "_column", "_values", "_indices")

    def __init__(self, df: "SimpleDataFrame", column: str, values: Sequence, indices: Sequence[int]):
        self._df = df
        self._column = column
        self._values = list(values)
        self._indices = list(indices)

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> Mask:  # type: ignore[override]
        return Mask(value == other for value in self._values)

    @property
    def iloc(self) -> _SeriesILoc:
        return _SeriesILoc(self)


class _Row:
    __slots__ = ("_data",)

    def __init__(self, data: dict):
        self._data = data

    def to_dict(self) -> dict:
        return dict(self._data)


class _ILocIndexer:
    __slots__ = ("_df",)

    def __init__(self, df: "SimpleDataFrame") -> None:
        self._df = df

    def __getitem__(self, index: int | slice):
        if isinstance(index, slice):
            rows = self._df._rows[index]
            return SimpleDataFrame(rows, columns=self._df._columns)
        return _Row(self._df._rows[index])


class _LocIndexer:
    __slots__ = ("_df",)

    def __init__(self, df: "SimpleDataFrame") -> None:
        self._df = df

    def __getitem__(self, key: tuple) -> Series:
        mask, column = key
        indices = self._df._mask_to_indices(mask)
        values = [self._df._rows[i].get(column) for i in indices]
        return Series(self._df, column, values, indices)

    def __setitem__(self, key: tuple, value) -> None:
        mask, column = key
        indices = self._df._mask_to_indices(mask)
        for idx in indices:
            self._df._rows[idx][column] = value


class SimpleDataFrame:
    __slots__ = ("_rows", "_columns")

    def __init__(self, rows: Sequence[dict], *, columns: Sequence[str] | None = None) -> None:
        self._rows = [dict(row) for row in rows]
        if columns is None:
            if rows:
                columns = list(rows[0].keys())
            else:
                columns = list(DEFAULT_COLUMNS)
        self._columns = list(columns)

    @property
    def empty(self) -> bool:
        return not self._rows

    def to_dict(self, orient: str = "records") -> list:
        if orient != "records":  # pragma: no cover - defensive fallback
            raise ValueError("Only records orient is supported")
        return [dict(row) for row in self._rows]

    def head(self, count: int) -> "SimpleDataFrame":
        return SimpleDataFrame(self._rows[:count], columns=self._columns)

    def __getitem__(self, key):
        if isinstance(key, str):
            values = [row.get(key) for row in self._rows]
            return Series(self, key, values, range(len(self._rows)))
        mask_values = self._mask_to_bools(key)
        rows = [self._rows[i] for i, keep in enumerate(mask_values) if keep]
        return SimpleDataFrame(rows, columns=self._columns)

    def _mask_to_bools(self, mask) -> List[bool]:
        if isinstance(mask, Mask):
            bools = mask.values
        elif isinstance(mask, Series):
            bools = [bool(value) for value in mask]
        elif isinstance(mask, Sequence):
            bools = [bool(value) for value in mask]
        else:  # pragma: no cover - defensive fallback
            raise TypeError("Unsupported mask type")
        if len(bools) != len(self._rows):
            raise ValueError("Mask length mismatch")
        return bools

    def _mask_to_indices(self, mask) -> List[int]:
        return [idx for idx, keep in enumerate(self._mask_to_bools(mask)) if keep]

    @property
    def iloc(self) -> _ILocIndexer:
        return _ILocIndexer(self)

    @property
    def loc(self) -> _LocIndexer:
        return _LocIndexer(self)

    def to_csv(self, path: Path | str, index: bool = False) -> None:  # noqa: ARG002
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._columns)
            writer.writeheader()
            for row in self._rows:
                writer.writerow({column: row.get(column, "") for column in self._columns})

    @classmethod
    def from_csv(cls, path: Path | str) -> "SimpleDataFrame":
        path = Path(path)
        if not path.exists():
            return cls([], columns=DEFAULT_COLUMNS)
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = [dict(row) for row in reader]
            columns = reader.fieldnames or list(DEFAULT_COLUMNS)
        return cls(rows, columns=columns)


def _ensure_dataframe(obj):
    if pd is not None and isinstance(obj, pd.DataFrame):
        return obj
    if isinstance(obj, SimpleDataFrame):
        return obj
    raise TypeError("Unsupported dataframe type")


def load_schedule():
    if not SCHEDULE_FILE.exists():
        if pd is not None:
            return pd.DataFrame(columns=list(DEFAULT_COLUMNS))
        return SimpleDataFrame([], columns=DEFAULT_COLUMNS)
    if pd is not None:
        return pd.read_csv(SCHEDULE_FILE)
    return SimpleDataFrame.from_csv(SCHEDULE_FILE)


def save_schedule(df):
    if pd is not None and isinstance(df, pd.DataFrame):
        df.to_csv(SCHEDULE_FILE, index=False)
    elif isinstance(df, SimpleDataFrame):
        df.to_csv(SCHEDULE_FILE, index=False)
    else:  # pragma: no cover - defensive fallback
        raise TypeError("Unsupported dataframe type for saving")


def list_available(date=None, limit=5):
    df = load_schedule()
    df = _ensure_dataframe(df)
    if df.empty:
        return []
    avail = df[df["status"] == "Available"]
    if date:
        avail = avail[avail["date"] == date]
    if avail.empty:
        return []
    return avail.head(limit).to_dict(orient="records")


def find_next_available(after_date):  # noqa: ARG001 - kept for API parity
    df = load_schedule()
    df = _ensure_dataframe(df)
    if df.empty:
        return None
    avail = df[df["status"] == "Available"]
    if avail.empty:
        return None
    return avail.iloc[0].to_dict()


def reserve_slot(date, start_time, name, appt_type):
    df = load_schedule()
    df = _ensure_dataframe(df)
    mask = (df["date"] == date) & (df["start_time"] == start_time)
    if not mask.any():
        return False
    if df.loc[mask, "status"].iloc[0] != "Available":
        return False
    df.loc[mask, "status"] = "Booked"
    df.loc[mask, "patient_name"] = name
    df.loc[mask, "appointment_type"] = appt_type
    save_schedule(df)
    BOOKINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with BOOKINGS_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"{date},{start_time},{name},{appt_type}\n")
    return True
