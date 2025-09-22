# Dental Voice Receptionist

A FastAPI + Twilio voice assistant that behaves like a natural, speech-first dental receptionist. Every caller hears a single, human opening, the bot remembers their context (intent, name, requested time), and finished calls are archived for review and self-improvement.

## Key features

- FastAPI webhooks on port **5173** with `/health`, `/voice`, `/gather-intent`, `/gather-booking`, and `/status` routes.
- One-and-done greeting with a short AI disclaimer and speech-only Twilio `<Gather>` prompts (barge-in enabled, no keypad menus).
- Practice configuration in `config/practice.yml` (name, voice, language, hours, address, prices) with environment overrides and Alice/en-GB fallbacks.
- Per-call memory keyed by `CallSid`, tracking transcripts, retries, recognised intent, caller name, and requested time.
- Automatic persistence when Twilio sends the status callback:
  - Plain-text transcripts stored in `transcripts/AI Incoming Call <index> <HH-mm> <dd-MM-yy>.txt` with `[Agent]` / `[Caller]` lines.
  - Bookings appended to `data/bookings.csv` (`timestamp, call_sid, caller_name, requested_time, intent`).
  - Call summaries appended to `data/calls.jsonl` (`call_sid, finished_at, direction, from, to, duration_sec, caller_name, intent, requested_time, transcript_file`).
- Availability & bookings
  - The assistant reads `data/schedule.csv` for free times.
  - Phrases like “what do you have tomorrow / on Wednesday” will list real times for that day.
  - Booking order: type → day → time → name → confirm. On confirm, the slot is marked **Booked** in `data/schedule.csv` and a line is appended to `data/bookings.csv`.
  - If a day is full, it suggests the next available slot.
- Optional webhook signature validation and JSON-formatted logging controlled via environment variables.
- Daily self-learning workflow that inspects transcripts, writes suggestions, and opens/updates a GitHub issue for review.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

A sample `.env.example` is included. Copy it to `.env` and adjust values as needed.

### Environment variables

| Variable | Description | Default |
| --- | --- | --- |
| `TTS_VOICE` | Preferred Twilio voice name. Overrides `config/practice.yml`. | `Polly.Amy` |
| `TTS_LANG` | Voice language/locale. Overrides `config/practice.yml`. | `en-GB` |
| `VERIFY_TWILIO_SIGNATURES` | Enable webhook signature validation (requires auth token). | `false` |
| `DEBUG_LOG_JSON` | Emit JSON logs instead of plain text. | `false` |
| `TWILIO_ACCOUNT_SID` | Optional reference for logging. | _unset_ |
| `TWILIO_AUTH_TOKEN` | Required when validating Twilio signatures. | _unset_ |

> When `VERIFY_TWILIO_SIGNATURES=true`, `TWILIO_AUTH_TOKEN` **must** be set or the server will refuse to start.

### Practice configuration

`config/practice.yml` ships with sample details for **Oak Dental**:

```yaml
practice_name: "Oak Dental"
voice: "Polly.Amy"
language: "en-GB"
hours: "We’re open Monday to Friday nine to five; Saturday ten to one; Sundays and bank holidays closed."
address: "12 High Street, Oakford, OX1 2AB."
prices: "Check-up forty five pounds, hygiene sixty five, whitening from two hundred and fifty."
```

Update these values to match your practice. `TTS_VOICE`/`TTS_LANG` in the environment always take precedence; if neither config nor environment specify a voice the app falls back to `alice` / `en-GB`.

## Running locally

```bash
uvicorn main:app --host 0.0.0.0 --port 5173 --reload
```

Visit `http://localhost:5173/health` to confirm the API is running.

### Exposing the webhook with ngrok

```bash
ngrok http 5173
```

Copy the HTTPS forwarding URL (for example `https://random.ngrok.app`) for the Twilio console configuration below. If ngrok restarts, update Twilio with the new URL.

## Twilio console configuration

1. In the [Twilio Console](https://console.twilio.com/), open **Phone Numbers → Manage → Active numbers** and select your number.
2. Under **Voice & Fax → A Call Comes In** set the webhook to `https://<your-ngrok-domain>/voice` and choose **HTTP POST**.
3. Under **Status Callback URL** set the webhook to `https://<your-ngrok-domain>/status` and choose **HTTP POST**.
4. Save changes and place a test call through the number.

## Call flow at a glance

- Greeting (played once): “Hi, thanks for calling our dental practice. I’m your AI receptionist, here to help with general information and booking appointments. Please note, I’m not a medical professional. How can I help you today? You can ask about our opening hours, our address, our prices, or say you’d like to book an appointment.”
- Intent handling:
  - “Hours”, “address”, and “prices” replies come directly from `config/practice.yml`, followed by “Is there anything else I can help with?”
  - “Book” triggers a short conversation: first name → preferred day/time → natural confirmation.
  - Unknown speech triggers the clarifier “Do you need our opening hours, address, prices, or would you like to book?”
- Silences: the first silence repeats the clarifier, the second asks “Is there anything else I can help with?”, and a third silence or “no” ends with a rotating polite goodbye (five variants).
- Confirmed bookings are logged immediately and acknowledged with “Brilliant… the team will confirm shortly.”

## Persistence outputs

Transcripts capture both sides of the conversation in real time: each agent prompt that is spoken and every caller utterance is
stored in memory until Twilio sends `/status` with `CallStatus=completed`, at which point the full transcript is flushed to disk.
While a call is active you can review the live state at `/_debug/state` and the in-progress transcript via
`/_debug/transcript?sid=<CallSid>` (local development only).

**Important:** Configure the Twilio phone number's **Status Callback (POST)** to point at `/status` — without it the transcript
file is never written.

When Twilio sends `/status` with `CallStatus=completed` the app:

1. Writes the transcript to `transcripts/AI Incoming Call <index> <HH-mm> <dd-MM-yy>.txt` using `[Agent]` / `[Caller]` lines.
2. Appends bookings to `data/bookings.csv` with the schema `timestamp, call_sid, caller_name, requested_time, intent`.
3. Adds a JSON line to `data/calls.jsonl` describing the call (`call_sid, finished_at, direction, from, to, duration_sec, caller_name, intent, requested_time, transcript_file`).

Directories are created automatically if they do not already exist.

## Daily self-learning workflow

- `scripts/learn.py` scans all transcripts for gaps (emergency keywords, bank holidays, SMS requests, etc.) and writes `codex_tasks/suggestions-YYYY-MM-DD.md`.
- `.github/workflows/daily-learn.yml` runs every day at 09:00 Europe/London (or via manual dispatch) to:
  1. Check out the repo and run the learning script.
  2. Commit the updated suggestions file if it changed.
  3. Open or update an issue titled **“Daily AI Receptionist improvements YYYY-MM-DD”** containing the suggestions plus a ready-to-paste **Codex Task** block asking for implementation in a follow-up PR.
- No code changes are made automatically—humans review the suggestions before acting.

You can also run the script locally:

```bash
python scripts/learn.py
```

## Testing

```bash
pytest
```

## Troubleshooting

- **405 Method Not Allowed** – Ensure Twilio webhooks are configured with HTTP POST for both `/voice` and `/status`.
- **502 / tunnel timeout** – Restart `ngrok http 5173` and update Twilio with the new forwarding URL.
- **403 signature validation failures** – Set `VERIFY_TWILIO_SIGNATURES=false` locally or provide the correct `TWILIO_AUTH_TOKEN`.
- **Polly voice missing** – The app falls back to `alice` automatically if Polly voices are unavailable; set `TTS_VOICE=alice` (or another supported voice) in your `.env` file to avoid repeated warnings.
- **No transcripts generated** – Confirm the FastAPI server is reachable from your public ngrok URL and that Twilio is sending the status callback.

## Troubleshooting & Dev

### Project folders
- `transcripts/` — per-call `.txt` transcripts written after each call.
- `data/` — generated `bookings.csv` and `calls.jsonl` summaries.
- `logs/` — rotating `app.log` output from the FastAPI app.

### Debug endpoints
- `GET /_debug/state` — returns the current in-memory call states (local only).
- `GET /_debug/logs?n=200` — streams the last `n` log lines (`n` defaults to 50).
- `GET /_debug/transcript?sid=<CallSid>` — shows the in-memory transcript for a specific call (local only).

### Watchers
- `python scripts/watch.py` (cross-platform log follower).
- `powershell -ExecutionPolicy Bypass -File .\scripts\watch.ps1 -Lines 200` (Windows tail).

> Debug endpoints are for local development only—do not expose them in production.
