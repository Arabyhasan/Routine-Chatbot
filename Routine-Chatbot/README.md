# Routine Agent

An AI-powered scheduling assistant that reads your routine, monitors Slack and Gmail for meeting requests, resolves conflicts using a priority engine, and keeps a live Google Sheets weekly view of your schedule — updated automatically.

Built as an internship project at Talentier exploring Claude tool-use, MCP server integration, and autonomous agent workflows.

---

## What it does

- **Natural language scheduling** — "can we meet at 8pm?" is parsed, checked against your routine, and replied to automatically
- **Priority-based conflict resolution** — a manager (e.g. Bijoy, priority 10) requesting your gym slot (priority 2) overrides it and reschedules; an unknown requester gets a polite decline with free-slot alternatives instead
- **Google Sheets sync** — a live weekly schedule (10 AM–10 PM, Mon–Sun with real dates) updates automatically every time a meeting is added, rescheduled, or cancelled; rolls to the next week every Monday
- **Slack and Gmail integration** — drafts and sends messages and emails via Claude
- **Multi-turn conversation** — context is kept across turns so follow-up messages work naturally
- **MCP server** — exposes all scheduling tools to Claude Desktop or any MCP-compatible host
- **Free to run** — works with Groq or Gemini if you don't have an Anthropic key

---

## Architecture

```
User message
    ↓
llm_provider.py — picks best available: Claude → Groq → Gemini
    ↓
LLM decides which tools to call (tool-use / function calling)
    ↓
mcp_tools.py — single source of truth for all tool logic
    ↓   ↓   ↓   ↓   ↓
routine  slack  gmail  sheets  priority engine
    ↓
LLM formulates natural language reply
    ↓
User
```

All tool implementations live in `mcp_tools.py`. Both the web chatbot (`chatbot.py`) and the MCP server (`mcp_server.py`) call the same functions — add a tool once and it's available everywhere.

---

## LLM providers (auto-selected from .env)

| Priority | Provider | Cost | Limits | Key |
|---|---|---|---|---|
| 1 | **Claude** (Anthropic) | Paid | Best tool-use quality | `ANTHROPIC_API_KEY` |
| 2 | **Groq** (Llama 3.3 70B) | **Free** | 14,400 req/day, no card | `GROQ_API_KEY` |
| 3 | **Gemini 2.0 Flash** (Google) | **Free** | Generous quota, Google account | `GEMINI_API_KEY` |

The app detects whichever key is set and uses it — no code changes needed to switch.

**Get a free Groq key in 30 seconds:** https://console.groq.com (just email, no credit card)

---

## Google Sheets weekly view

The agent maintains one persistent spreadsheet titled **"Routine Agent — Weekly Schedule"** in your Google Drive.

- Columns: Mon–Sun with real dates (current week, Monday-anchored)
- Rows: 10:00 AM → 10:00 PM in 30-minute steps
- 🟢 Green = free slot
- 🟠 Orange = reschedulable commitment (gym, deep work, lunch)
- 🔴 Red = fixed commitment (university class, locked meetings)
- 🔵 Blue header = today's column
- Header row and Time column are frozen for easy scrolling
- Rolls automatically to the next week every Monday

Auto-syncs after every mutation — schedule a meeting, the sheet updates within seconds.

---

## Priority system

Defined entirely in `config.yaml` — no hardcoded logic anywhere.

```yaml
requesters:
  bijoy:
    priority: 10      # manager — can override gym, deep work, etc.
    relationship: "manager"

commitments:
  gym:
    priority: 2       # low — can be moved by high-priority requesters
    reschedulable: true
  class:
    priority: 9       # high — never moved, even by manager
    reschedulable: false

conflict_resolution:
  manager_override_threshold: 8   # requester needs >= this to override anything
  max_reschedulable_priority: 6   # only reschedule commitments at or below this
```

**Decision logic:**
- Slot is free → confirm immediately
- Slot is taken + requester priority ≥ threshold + commitment is reschedulable + commitment priority ≤ max → reschedule and confirm
- Anything else → decline, offer free-slot alternatives

---

## Tools available to the agent (15 total)

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
| `sync_to_sheets` | Force a full Google Sheets sync |
| `remember_fact` | Store a preference or fact |
| `recall_memory` | Recall stored context |
| `get_configured_requesters` | Show priority config |
| `health_check` | Check which services are connected |

---

## Setup

**Python 3.11+ required**

```bash
git clone https://github.com/Arabyhasan/Routine-Chatbot.git
cd Routine-Chatbot
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` — minimum needed to run:

```env
# Free option (no credit card):
GROQ_API_KEY=gsk_...        # get from https://console.groq.com

# Or paid:
# ANTHROPIC_API_KEY=sk-ant-...
```

---

## Run

**Web chatbot** → http://localhost:8000
```bash
python web_app.py
```

**Terminal mode**
```bash
python chatbot.py
```

**MCP server** (for Claude Desktop integration)
```bash
python mcp_server.py
```

---

## Optional integrations

### Slack
```env
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_IDS=meeting-times,general
```
Create a Slack app at https://api.slack.com/apps, add `chat:write` and `channels:read` OAuth scopes.

### Gmail + Google Sheets
```bash
# 1. Download credentials.json from Google Cloud Console
#    (Enable Gmail API + Google Sheets API + Google Drive API)
# 2. Run the auth flow once:
python google_integration.py
# 3. This creates token.json — keep it, don't commit it
```
Required scopes: `gmail.send`, `gmail.readonly`, `calendar`, `spreadsheets`, `drive.file`

> If you already have a `token.json` from before Sheets was added, delete it and re-run `python google_integration.py` to pick up the new scopes.

---

## File layout

| File | Role |
|---|---|
| `llm_provider.py` | Auto-selects Claude / Groq / Gemini, converts message formats |
| `chatbot.py` | Agent loop — calls LLM, executes tools, manages history |
| `mcp_tools.py` | All 15 tool implementations (single source of truth) |
| `mcp_server.py` | MCP server — thin wrappers around mcp_tools.py |
| `web_app.py` | Browser UI at localhost:8000 with Sheet sync button |
| `sheets_integration.py` | Google Sheets weekly schedule builder and auto-sync |
| `priority.py` | Conflict resolution engine |
| `availability.py` | Free slot detection (10 AM–10 PM window) |
| `routine_manager.py` | Read/write routine.json |
| `config_loader.py` | Load config.yaml |
| `email_agent.py` | Email drafting via LLM |
| `slack_integration.py` | Slack API wrapper |
| `google_integration.py` | Gmail, Calendar, and Sheets OAuth + service clients |
| `knowledge_base.py` | Memory and user preferences |
| `models.py` | Shared data classes (Commitment, TimeSlot, etc.) |
| `service_config.py` | Which integrations are enabled |
| `config.yaml` | Priority rules and requester config (edit here, no code changes) |
| `routine.json` | Your schedule — human-editable directly |
| `.env.example` | Template for environment variables |
