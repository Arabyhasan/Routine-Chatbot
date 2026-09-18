# Routine Agent

A Gemini-first Python assistant for routine management, meeting coordination, and service-aware automation.

## Overview

This project builds a personal scheduling and communication assistant that can:

- understand natural-language scheduling requests,
- detect and resolve conflicts between meetings and recurring commitments,
- offer free time suggestions and proposal handling,
- reschedule lower-priority commitments when higher-priority requests arrive,
- parse recurring patterns such as "gym every day at 7 except Friday",
- validate emails before drafting or sending them,
- interact with Slack, Gmail, and Google Calendar,
- expose schedule data through an MCP server,
- use Gemini as the live reasoning engine for chat-based interaction.

The design keeps the LLM in the reasoning and interpretation layer while the project’s own scheduling engine remains the execution source of truth.

## Architecture

- `chatbot.py` — main conversational assistant and user entry point
- `automation_worker.py` — background Slack/Gmail automation loop
- `knowledge_base.py` — centralized default behavior, runtime policy, and reusable assistant logic
- `message_parser.py` — extracts meeting times and recurring routine instructions from natural language
- `priority.py` — conflict resolution and meeting decision logic
- `availability.py` — free-slot detection and availability checks
- `routine_manager.py` — routine persistence and updates
- `models.py` — shared data models for commitments, meeting requests, and decisions
- `config_loader.py` — config-driven scheduling rules and requester metadata
- `slack_integration.py` — Slack API wrapper
- `google_integration.py` — Gmail and Calendar API wrapper
- `mcp_server.py` — local MCP tool layer for routine and availability queries
- `email_agent.py` — validation and draft generation
- `main.py` — startup entry point for the interactive chatbot

## Core Features

### Scheduling and conflict handling
The assistant loads recurring commitments from `routine.json` and checks for free slots based on the user’s schedule. If a meeting request conflicts with an existing commitment, the bot evaluates whether the requester has the priority and whether the commitment is reschedulable.

### Recurring commitments
The parser supports natural-language recurring instructions such as:

- "I have gym every day at 7 except Friday"
- "Daily workout at 7 pm"

These are turned into structured routine entries and persisted in the local schedule.

### No-meetings-today flow
When a user says no meetings should be scheduled for the day, the assistant clears conflicts for that day and moves any overlapping items to the next day at the same time where needed.

### Email confirmation flow
The assistant validates addresses before creating or sending an email. It drafts the message and waits for explicit confirmation before sending it.

### Slack and Gmail automation
The app can be configured to run the worker in Slack-only, Gmail-only, or combined modes. Messages are processed, routed through the assistant, and sent back to the correct service.

### Gemini-first default routing
The runtime policy is configured to default to Gemini for the live reasoning layer. The project’s local logic remains the execution layer so the assistant stays predictable and safe.

## Setup

### Dependencies

This project is designed for Python 3.12 and uses the local environment installed in the project workspace.

### Local secrets
Create a local `.env` file with your credentials, for example:

```env
GEMINI_API_KEY=your_gemini_key_here
SLACK_BOT_TOKEN=your_slack_bot_token
SLACK_APP_TOKEN=your_slack_app_token
SLACK_SIGNING_SECRET=your_slack_signing_secret
GOOGLE_CALENDAR_CREDENTIALS_PATH=credentials.json
GOOGLE_CALENDAR_TOKEN_PATH=token.json
```

Do not commit `.env`, token files, or credential files. The repository is configured to ignore them.

## Run the app

```bash
python main.py
```

## Test the project

```bash
python -m pytest -q
```

## Notes

This project was built as a practical scheduling and workflow assistant that blends LLM reasoning with deterministic local logic. That makes it useful for real coordination tasks while keeping operations explainable, testable, and easier to extend by future users.
