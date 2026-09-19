# Routine Agent

An AI scheduling assistant powered by Claude — monitors Slack and Gmail for meeting requests, manages a priority-based routine, auto-replies, and keeps your schedule updated.

Built as an internship project at Talentier to explore Claude tool-use, MCP server integration, and autonomous agent workflows.

---

## What it does

- **Understands natural language** — "can we meet at 8pm?" gets parsed, checked against your routine, and replied to automatically
- **Priority-based conflict resolution** — a manager requesting your gym slot overrides it and reschedules; an unknown requester gets a polite decline with free-slot alternatives
- **Reads and writes your routine** — commitments live in `routine.json` and get updated when meetings are confirmed or rescheduled
- **Sends Slack messages and emails** — drafts via Claude, confirms before sending
- **Remembers context** — conversation history is kept across turns so follow-up messages work naturally
- **MCP server** — exposes all scheduling tools to Claude Desktop or any MCP-compatible host

---

## Architecture

```
User message
    ↓
Claude (claude-haiku-4-5) — reads intent, decides which tools to call
    ↓
mcp_tools.py — single source of truth for all tool logic
    ↓   ↓   ↓   ↓
routine  slack  gmail  priority engine
    ↓
Claude — formulates natural language reply
    ↓
User
```

All tool implementations live in `mcp_tools.py`. Both the web chatbot (`chatbot.py`) and the MCP server (`mcp_server.py`) call the same functions — change a tool once, updated everywhere.

---

## Priority system

Defined entirely in `config.yaml` — no hardcoded logic.

Two dimensions:
- **Requester priority** (1–10): Bijoy (manager) = 10, unknown = 1
- **Commitment priority** (1–10): gym = 2, class = 9

Override rule: if `requester_priority >= manager_override_threshold` AND the commitment is reschedulable AND its priority is below the sacred threshold → reschedule and confirm. Otherwise → decline and offer free slots.

---

## Tools available to Claude

| Tool | What it does |
|---|---|
| `read_schedule` | Load commitments for a day |
| `check_time_slot` | Is a specific time free? |
| `get_free_slots` | What times are open today? |
| `schedule_meeting` | Book via priority engine |
| `reschedule_commitment` | Move an existing item |
| `cancel_commitment` | Remove from routine |
| `add_recurring_commitment` | Add gym every weekday at 8pm |
| `send_slack_message` | Post to a Slack channel |
| `send_email` | Draft + optionally send via Gmail |
| `confirm_pending_email` | Confirm or cancel a pending draft |
| `remember_fact` | Store a preference or fact |
| `recall_memory` | Recall stored context |
| `get_configured_requesters` | Show priority config |
| `health_check` | Check which services are connected |

---

## Setup

**Requirements:** Python 3.11+

```bash
pip install anthropic python-dotenv pyyaml slack-sdk google-auth google-auth-oauthlib google-api-python-client mcp
```

Create a `.env` file:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_IDS=meeting-times,general

# Optional — run `python google_integration.py` to generate token.json
GOOGLE_CALENDAR_CREDENTIALS_PATH=credentials.json
GOOGLE_CALENDAR_TOKEN_PATH=token.json
```

---

## Run

**Web chatbot** (http://localhost:8000):
```bash
python web_app.py
```

**Terminal mode:**
```bash
python chatbot.py
```

**MCP server** (for Claude Desktop):
```bash
python mcp_server.py
```

**Tests:**
```bash
python -m pytest -q
```

---

## File layout

| File | Role |
|---|---|
| `chatbot.py` | Claude agent loop — tool-use orchestration |
| `mcp_tools.py` | All tool implementations (single source of truth) |
| `mcp_server.py` | MCP server — thin wrappers around mcp_tools.py |
| `web_app.py` | Browser UI at localhost:8000 |
| `priority.py` | Conflict resolution engine |
| `availability.py` | Free slot detection |
| `routine_manager.py` | Read/write routine.json |
| `config_loader.py` | Load config.yaml |
| `email_agent.py` | Email drafting via Claude |
| `slack_integration.py` | Slack API wrapper |
| `google_integration.py` | Gmail and Calendar integration |
| `knowledge_base.py` | Memory and preferences |
| `config.yaml` | Priority rules and requester config |
| `routine.json` | Your schedule (editable directly) |

---

## Config

Edit `config.yaml` to change behavior — no code changes needed:

```yaml
requesters:
  bijoy:
    display_name: "Bijoy"
    priority: 10          # manager — can override gym, deep work, etc.
    relationship: "manager"

commitments:
  gym:
    priority: 2           # low — can be moved by high-priority requesters
    reschedulable: true
  class:
    priority: 9           # high — never moved, even by manager
    reschedulable: false

conflict_resolution:
  manager_override_threshold: 8   # requester needs >= this to override anything
  max_reschedulable_priority: 6   # only reschedule commitments at or below this
```
