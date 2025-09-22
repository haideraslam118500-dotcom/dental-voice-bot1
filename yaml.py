from __future__ import annotations

from typing import Any, Dict


class YAMLError(Exception):
    """Fallback YAML error used by the local stub."""


def safe_load(data: str | bytes) -> Dict[str, Any]:
    if isinstance(data, bytes):
        text = data.decode("utf-8")
    else:
        text = str(data)
    result: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise YAMLError(f"Unable to parse line: {raw_line}")
        key = key.strip()
        value = value.strip()
        if value.startswith("\"") and value.endswith("\""):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        result[key] = value
    return result
