# Dental Voice Receptionist

A FastAPI application that turns a Twilio voice number into a warm, UK-style dental receptionist. The assistant greets callers with varied openings, handles hours/address/prices/booking questions, captures booking details, keeps a running transcript, and learns from each day of calls.

## Key features

- FastAPI webhooks on port **5173** with `/health`, `/voice`, `/gather-intent`, `/gather-booking`, and `/status` routes.
- Speech-first Twilio `<Gather>` prompts with barge-in support, keypad shortcuts, and varied conversational fillers.
- Environment-driven Polly voice selection (default `Polly.Amy` with `alice` fallback) and short, natural UK prompts.
- Per-call memory keyed by `CallSid`, including transcripts, caller name, intent, requested time, and retry counters.
- Automatic persistence:
  - Plain-text transcripts saved in `transcripts/` (Windows-safe filenames).
  - Booking attempts appended to `data/bookings.csv`.
  - Completed call summaries appended to `data/calls.jsonl`.
- Optional Twilio signature validation and structured JSON logging.
- Daily self-learning loop that inspects transcripts, writes suggestions, and opens/updates a GitHub issue for human review.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### Environment variables (.env support)

The app reads a `.env` file automatically. Create `.env` (or export variables manually) with the settings you need:

| Variable | Description | Default |
| --- | --- | --- |
| `TTS_VOICE` | Preferred Twilio voice name. | `Polly.Amy` |
| `TTS_LANG` | Voice language/locale. | `en-GB` |
| `VERIFY_TWILIO_SIGNATURES` | Enable webhook signature validation (requires auth token). | `false` |
| `DEBUG_LOG_JSON` | Emit JSON logs instead of plain text. | `false` |
| `TWILIO_AUTH_TOKEN` | Auth token for signature validation. | _unset_ |
| `TWILIO_ACCOUNT_SID` | Account SID for reference/logging. | _unset_ |
| `TWILIO_NUMBER` | The Twilio phone number handling calls. | _unset_ |

> When `VERIFY_TWILIO_SIGNATURES=true`, `TWILIO_AUTH_TOKEN` **must** be set or the server will refuse to start.

## Running locally

```bash
uvicorn main:app --host 0.0.0.0 --port 5173 --reload
```

Visit `http://localhost:5173/health` for a quick status check.

### Exposing the webhook with ngrok

```bash
ngrok http 5173
```

Copy the HTTPS forwarding URL (for example `https://random.ngrok.app`) for the Twilio console configuration below. If ngrok restarts and you see 502 errors from Twilio, update the console with the new URL.

## Twilio console configuration

1. In the [Twilio Console](https://console.twilio.com/), open **Phone Numbers → Manage → Active numbers** and select your number.
2. Under **Voice & Fax → A Call Comes In**:
   - Set the webhook URL to `https://<your-ngrok-domain>/voice`.
   - Choose **HTTP POST**.
3. Under **Status Callback URL**:
   - Set the URL to `https://<your-ngrok-domain>/status`.
   - Choose **HTTP POST**.
4. Save changes and place a test call through the number.

## How the receptionist behaves

- 10–15 varied greetings are chosen at random per call, all in a friendly UK tone.
- `<Gather>` prompts accept both speech and DTMF (1–4) with barge-in enabled so callers can interrupt.
- The bot answers questions about opening hours, address, and prices using:
  - `HOURS_LINE`: “We're open Monday to Friday, nine till five; Saturdays ten till two; Sundays closed.”
  - `ADDRESS_LINE`: “We're at 12 Market Street, Central Milton Keynes, MK9 3QA.”
  - `PRICES_LINE`: “A checkup starts from sixty pounds, hygiene from seventy-five, and white fillings from one hundred and twenty.”
- Booking intent waits to hear a preferred name and time, then confirms and checks if anything else is needed before hanging up.
- Clarifiers are conversational (“Sorry, could you say that again?”) instead of hard error strings, and two consecutive silences trigger a polite “Is there anything else I can help you with?” check before saying goodbye.

## Persistence outputs

After each completed call (`/status` with `CallStatus=completed`):

- A transcript is written to `transcripts/AI Incoming Call <index> <HH-mm> <dd-MM-yy>.txt`.
- Booking attempts append to `data/bookings.csv` with columns `timestamp, call_sid, caller_name, requested_time, intent`.
- A JSON line is added to `data/calls.jsonl` summarising `call_sid, finished_at, direction, from, to, duration_sec, caller_name, intent, requested_time, transcript_file`.

Folders are created automatically if they do not already exist.

## Daily self-learning loop

- `scripts/learn.py` scans transcripts for gaps (emergency care, bank holidays, SMS confirmations, etc.) and writes `codex_tasks/suggestions-YYYY-MM-DD.md`.
- `.github/workflows/daily-learn.yml` runs every day at 09:00 Europe/London (or via manual dispatch) to:
  1. Execute the learning script.
  2. Commit the new suggestions file if it changed.
  3. Open or refresh an issue titled **“Daily AI Receptionist improvements YYYY-MM-DD”** with the suggestions plus a ready-to-paste **Codex task** block asking for a follow-up PR.
- No code changes are made automatically—humans review the suggestions and decide what to implement.

You can also run the script locally:

```bash
python scripts/learn.py
```

## Testing

```bash
pytest
```

GitHub Actions (`.github/workflows/tests.yml`) runs the same suite on pushes to `main` and every pull request.

## Troubleshooting

- **405 Method Not Allowed** – Ensure Twilio webhooks are configured with HTTP POST for `/voice` and `/status`.
- **502 / tunnel timeout** – Restart `ngrok http 5173` and update the Twilio console with the new forwarding URL.
- **403 signature validation failures** – Set `VERIFY_TWILIO_SIGNATURES=false` locally or provide the correct `TWILIO_AUTH_TOKEN` when validating requests.
- **Polly voice missing** – If Polly voices are not enabled on your Twilio account, set `TTS_VOICE=alice` (or another available voice) in your `.env` file.
- **No transcripts generated** – Confirm the FastAPI server is running on port 5173 and reachable from the public URL configured in Twilio.

## Next steps

- Expand the intent model for emergencies, payment plans, or treatment-specific FAQs.
- Hook booking confirmations into your actual practice management system.
- Review daily suggestion issues and feed accepted improvements into new PRs.
