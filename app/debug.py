from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pathlib import Path
from typing import Optional
import itertools

router = APIRouter()

ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / "logs" / "app.log"

# main.py will import CALLS; for type-ignore here
try:
    from main import CALLS  # type: ignore
except Exception:
    CALLS = {}


@router.get("/_debug/state")
def debug_state():
    # Shallow copy for safety
    try:
        snapshot = {k: {kk: vv for kk, vv in v.items() if kk != "transcript"} for k, v in CALLS.items()}
    except Exception:
        snapshot = {}
    return JSONResponse(snapshot)


@router.get("/_debug/logs")
def debug_logs(n: Optional[int] = Query(50, ge=1, le=500)):
    if not LOG_FILE.exists():
        return PlainTextResponse("No logs yet.", status_code=200)
    # Efficient tail without reading whole file
    lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    tail = list(itertools.islice(lines, max(0, len(lines) - (n or 50)), None))
    return PlainTextResponse("\n".join(tail), status_code=200)
