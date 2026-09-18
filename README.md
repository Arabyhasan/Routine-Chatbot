# Routine Agent

A Gemini-first personal productivity assistant for routine management, meeting coordination, Slack messaging, Gmail drafting, and Google Calendar workflows.

## Overview

This project is a practical AI assistant for daily planning and communication. It can:

- understand natural-language scheduling requests,
- detect whether the user means a meeting or a plain message,
- keep a sticky send target for mail vs. Slack DM until it is actually sent,
- manage recurring commitments and routine updates,
- suggest and resolve free-time slots,
- validate email addresses before drafting or sending an email,
- send Slack channel or DM messages,
- draft email replies using an AI model and confirm before sending,
- integrate with Google Calendar and Gmail,
- reason through chat requests using Gemini as the live intelligence layer.

The architecture intentionally keeps LLM reasoning on the interpretation layer while the local scheduling engine stays as the execution source of truth.

## Core capabilities

### Scheduling and routine management
- parse recurring instructions like "gym every day at 7 except Friday"
- load and persist a routine from `routine.json`
- check availability and free slots for the day
- detect and resolve conflicts between priorities and commitments

### Natural-language intent handling
- distinguish between real meeting requests and plain Slack sends
- keep the target sticky based on the active "send" intent
- support patterns like "send a mail ..." and "send a dm ..." without misclassifying them as meeting requests

### Communication workflows
- validate email addresses before drafting/sending a message
- generate refined email drafts using the AI model layer
- send Slack messages to the configured channel or DM target
- connect to Gmail and Google Calendar when credentials are configured

### Knowledge memory
- remember preferences and facts in a local knowledge base
- use that context to answer general assistant questions more naturally

## Repository layout

- `chatbot.py` — main conversation and orchestration logic
- `web_app.py` — browser-based app interface
- `automation_worker.py` — background automation loop and service routing
- `slack_integration.py` — Slack API wrapper
- `google_integration.py` — Gmail and Calendar integration
- `email_agent.py` — email validation and drafting logic
- `message_parser.py` — natural-language parsing for time and recurring commitments
- `priority.py` — meeting prioritization and scheduling decisions
- `availability.py` — free-slot detection
- `routine_manager.py` — routine persistence and updates
- `knowledge_base.py` — memory and profile context
- `mcp_server.py` — local MCP tool layer for schedule queries
- `config_loader.py` — config-driven runtime settings
- `service_config.py` — service toggles and defaults
- `main.py` — interactive console entry point

## Setup

### Requirements

This project is designed for Python 3.12.

### Local secrets
Create a local `.env` file with the values you need, for example:

```env
GEMINI_API_KEY=your_gemini_key_here
SLACK_BOT_TOKEN=your_slack_bot_token
SLACK_APP_TOKEN=your_slack_app_token
SLACK_SIGNING_SECRET=your_slack_signing_secret
GOOGLE_CALENDAR_CREDENTIALS_PATH=credentials.json
GOOGLE_CALENDAR_TOKEN_PATH=token.json
```

Do not commit `.env`, OAuth token files, or credential files. The repo ignores those paths.

## Run

```bash
python main.py
```

or launch the browser interface:

```bash
python web_app.py
```

## Test

```bash
python -m pytest -q
```

## Notes

This project blends LLM reasoning with deterministic local workflow logic so it remains useful for real coordination tasks without becoming a black box. The result is a practical assistant that can handle scheduling, messaging, and planning in a controlled, verifiable way.
