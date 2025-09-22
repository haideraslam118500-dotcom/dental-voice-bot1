from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Set
from zoneinfo import ZoneInfo

TRANSCRIPTS_DIR = Path("transcripts")
OUTPUT_DIR = Path("codex_tasks")
TIMEZONE = ZoneInfo("Europe/London")

KEYWORD_SUGGESTIONS = {
    "emergency": "Callers mentioned emergency care. Add clear guidance on urgent appointments and escalation steps.",
    "urgent": "Clarify how urgent or same-day appointments are handled.",
    "bank holiday": "Explain bank holiday opening hours or voicemail options.",
    "holiday": "Document bank holiday hours to avoid confusion.",
    "sunday": "Confirm whether Sunday cover is available or how to reach the team.",
    "weekend": "Share weekend availability and how callers can arrange cover.",
    "sms": "Offer SMS confirmations or follow-up texts when callers request them.",
    "text": "Explain whether SMS confirmations are available and how they work.",
    "whatsapp": "Consider enabling WhatsApp or messaging confirmations for bookings.",
    "insurance": "Provide a concise line covering insurance and payment plan questions.",
    "finance": "Clarify finance and payment plan options for callers.",
    "parking": "Add parking directions or nearby parking tips to the script.",
    "email": "Let callers know how to get email confirmations or send documents.",
}


def _scan_transcripts(paths: Iterable[Path]) -> Set[str]:
    hits: Set[str] = set()
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8").lower()
        except OSError:
            continue
        for keyword, suggestion in KEYWORD_SUGGESTIONS.items():
            if keyword in text:
                hits.add(suggestion)
    return hits


def _fallback_suggestions(has_transcripts: bool) -> List[str]:
    if has_transcripts:
        return [
            "No clear gaps detected today. Review tone, empathy, and flow for subtle improvements.",
        ]
    return [
        "No transcripts were found today; confirm Twilio is pointing at the webhook and calls are reaching the bot.",
    ]


def main() -> Path:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    transcript_paths = sorted(TRANSCRIPTS_DIR.glob("*.txt"))
    suggestions = sorted(_scan_transcripts(transcript_paths))
    has_transcripts = bool(transcript_paths)
    if not suggestions:
        suggestions = _fallback_suggestions(has_transcripts)

    now = datetime.now(tz=TIMEZONE)
    today_str = now.date().isoformat()
    output_path = OUTPUT_DIR / f"suggestions-{today_str}.md"

    header = f"# Daily AI Receptionist Suggestions - {today_str}\n"
    generated_line = f"Generated at {now.strftime('%H:%M %Z')} on {today_str}.\n"

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(header)
        handle.write("\n")
        handle.write(generated_line)
        handle.write("\n")
        for suggestion in suggestions:
            handle.write(f"- {suggestion}\n")

    return output_path


if __name__ == "__main__":
    path = main()
    print(path)
