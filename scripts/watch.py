import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "app.log"
print(f"Watching: {LOG}")
last_size = 0
while True:
    try:
        if LOG.exists():
            size = LOG.stat().st_size
            if size > last_size:
                with LOG.open("r", encoding="utf-8", errors="ignore") as f:
                    f.seek(last_size)
                    chunk = f.read()
                    if chunk:
                        print(chunk, end="")
                last_size = size
        time.sleep(0.5)
    except KeyboardInterrupt:
        break
