import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os
import json

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers on reload
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return

    # File handler (rotating)
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_fmt = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    # Optional JSON to stdout
    if os.getenv("DEBUG_LOG_JSON", "false").lower() == "true":
        class JsonFormatter(logging.Formatter):
            def format(self, record):
                payload = {
                    "timestamp": self.formatTime(record, self.datefmt),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                return json.dumps(payload)
        stream = logging.StreamHandler()
        stream.setFormatter(JsonFormatter())
        logger.addHandler(stream)
