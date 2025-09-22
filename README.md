# AI Receptionist for Dental Practices

A production-ready FastAPI application that answers inbound Twilio Voice calls for dental practices. The assistant greets callers, captures their name, identifies intent (hours, address, prices, or booking) and, when booking, gathers a preferred appointment time before handing off to staff.

## Features

- FastAPI webhooks with short, UK-friendly prompts rendered with Amazon Polly Amy (fallback to Alice).
- Intent flow with retry logic for first name, intent selection, and booking time capture.
- In-memory call state tracking keyed by `CallSid`, persisted to SQLite once the call completes.
- Optional Twilio signature validation middleware.
- Structured logging with optional JSON output for log aggregators.
- Automated unit tests and GitHub Actions workflow running `pytest` on each PR.

## Project structure

```
app/
  config.py          # Environment driven settings (logging, signatures, DB path)
  intent.py          # Basic speech/digit intent parsing
  logging_config.py  # Text vs JSON logging configuration
  persistence.py     # SQLite schema + persistence helpers
  security.py        # Twilio signature validation middleware
  state.py           # In-memory call state store
  twiml.py           # Focused TwiML builders used across the flow
main.py              # FastAPI application wiring the endpoints together
```

## Prerequisites

- Python 3.11+
- A Twilio account with a voice-enabled phone number
- (Optional) [ngrok](https://ngrok.com/) for local tunnelling

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### Environment variables

Create a `.env` file (or export variables in your shell) with the following values:

| Variable | Description | Default |
| --- | --- | --- |
| `VERIFY_TWILIO_SIGNATURES` | Enable Twilio webhook signature verification in production. Requires `TWILIO_AUTH_TOKEN`. | `false` |
| `DEBUG_LOG_JSON` | Emit structured JSON logs instead of plain text. | `false` |
| `TWILIO_ACCOUNT_SID` | Twilio account SID (used for reference/logging). | _unset_ |
| `TWILIO_AUTH_TOKEN` | Twilio auth token used for signature validation. | _unset_ |
| `TWILIO_NUMBER` | Your Twilio phone number in E.164 format. | _unset_ |
| `CALLS_DB_PATH` | (Optional) Override location of the SQLite database. | `data/calls.sqlite` |

> **Signature validation:** When `VERIFY_TWILIO_SIGNATURES=true`, the app requires `TWILIO_AUTH_TOKEN` to be set. This should match the token from your Twilio console so the middleware can validate the `X-Twilio-Signature` header on every webhook.

Load the environment variables before running the app:

```bash
export $(grep -v '^#' .env | xargs)  # if using a .env file
```

## Running the application

Start the API on the required port:

```bash
uvicorn main:app --host 0.0.0.0 --port 5173 --reload
```

### Exposing locally with ngrok

```bash
ngrok http 5173
```

Copy the HTTPS forwarding URL (for example `https://random.ngrok.app`) for the Twilio console configuration below. Remember that ngrok URLs change on each restart—update Twilio if you see 502 errors.

## Twilio console configuration

1. In the [Twilio Console](https://console.twilio.com/), open **Phone Numbers → Manage → Active numbers**.
2. Choose your incoming number.
3. Under **Voice & Fax → A Call Comes In**:
   - Set the webhook URL to `https://<your-ngrok-domain>/voice`.
   - Change the method to **HTTP POST**.
4. Under **Status Callback URL**:
   - Set the URL to `https://<your-ngrok-domain>/status`.
   - Change the method to **HTTP POST**.
5. Save changes.

## Call flow overview

1. `/voice` greets the caller and gathers their first name (speech).
2. `/gather-intent` thanks them by name and gathers intent (speech or DTMF 1–4). Retries twice with crisper prompts if unclear.
3. `/gather-booking` captures a requested date and time for booking intents, again retrying twice before escalating.
4. `/status` receives call lifecycle events. When status is `Completed`, the call state is written to `data/calls.sqlite` and in-memory state is cleared.

Each TwiML response keeps prompts short (~7 seconds) and speech-first, with optional keypad shortcuts.

## Logging & persistence

- Logs are INFO level by default. Set `DEBUG_LOG_JSON=true` for JSON output suited to log aggregation.
- Call summaries persist automatically at the end of each call in SQLite (`data/calls.sqlite`). The schema is:

```sql
CREATE TABLE calls (
    call_sid TEXT PRIMARY KEY,
    caller TEXT,
    intent TEXT,
    requested_time TEXT,
    finished_at TEXT
);
```

## Running tests

```bash
pytest
```

GitHub Actions (`.github/workflows/tests.yml`) automatically runs the same test suite on pushes to `main` and on every pull request.

## Troubleshooting

- **405 Method Not Allowed** – Ensure Twilio webhooks are set to use HTTP POST for `/voice` and `/status`.
- **502 Bad Gateway / stale tunnel** – Restart `ngrok http 5173` and update the Twilio console with the new forwarding URL.
- **Signature validation failures (403)** – Double-check `VERIFY_TWILIO_SIGNATURES` and that `TWILIO_AUTH_TOKEN` matches the token in the Twilio console. Disable verification locally if you're testing without a stable public URL.
- **Missing call transcripts** – Confirm the server is running on port 5173 and reachable from the public URL you configured in Twilio.

## Next steps

- Connect the booking intent to a real scheduling system.
- Push call summaries into your CRM or alerting pipeline.
- Extend prompts and intents to cover additional FAQs.
