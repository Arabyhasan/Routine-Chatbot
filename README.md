# Routine Chatbot

A Python personal assistant for daily scheduling, service-aware automation, and AI-powered email drafting.

## What it does
- Reads and manages a daily routine from `routine.json`
- Checks available time slots for meetings and reschedules lower-priority items when needed
- Supports Slack, Gmail, and Google Calendar integration
- Routes user requests through a small intent system
- Uses Claude via the Anthropic API to draft emails for valid addresses
- Provides a terminal chatbot interface and basic background worker flow

## Key files
- `chatbot.py` – main assistant logic and chat flow
- `priority.py` – scheduling and conflict resolution rules
- `routine_manager.py` – routine persistence
- `email_agent.py` – email validation and Claude-backed drafting
- `automation_worker.py` – background service worker logic
- `slack_integration.py` / `google_integration.py` – external service integrations
- `config.yaml` – priority and requester configuration

## Run locally

```bash
python chatbot.py
```

## Test

```bash
python -m pytest -q
```

## Environment
Add your local secrets in a `.env` file, for example:

```env
ANTHROPIC_API_KEY=your_claude_key_here
SLACK_BOT_TOKEN=your_slack_token
```

The repo intentionally ignores local secret files so credentials stay off GitHub.
