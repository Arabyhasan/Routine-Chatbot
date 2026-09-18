# Routine Agent

A Python-based scheduling assistant that reads a daily routine, checks availability, handles meeting requests, and applies configurable priority rules for conflict resolution.

## Features
- Reads routine data from `routine.json`
- Checks free slots for the day
- Handles meeting requests with manager override logic
- Supports a simple terminal chatbot demo
- Uses config-driven requester and commitment priority rules

## Run

```bash
python chatbot.py
```

## Test

```bash
python -m pytest -q
```

## Architecture
- `config.yaml` stores priority rules and requester metadata
- `routine.json` stores recurring commitments
- `priority.py` contains the scheduling decision engine
- `chatbot.py` provides a simple conversational demo
