# How to apply these fixes to your repo

## Option A — copy files directly (simplest)
```bash
cd Routine-Chatbot
git checkout Diffrent

# Replace the 4 fixed files:
cp ~/Downloads/chatbot.py .
cp ~/Downloads/web_app.py .
cp ~/Downloads/mcp_server.py .
cp ~/Downloads/email_agent.py .

git add chatbot.py web_app.py mcp_server.py email_agent.py
git commit -m "Fix: Claude tool-use agent, fix repeat bug, fix model names"
git push origin Diffrent
```

## Setup after applying

1. Copy `.env.example` → `.env` and fill in your keys:
```
ANTHROPIC_API_KEY=sk-ant-...    ← required
SLACK_BOT_TOKEN=xoxb-...        ← optional
```

2. Install deps:
```bash
pip install anthropic python-dotenv pyyaml slack-sdk google-auth google-auth-oauthlib google-api-python-client mcp
```

3. Run:
```bash
python web_app.py       # web UI at http://localhost:8000
python chatbot.py       # terminal mode
python mcp_server.py    # MCP server for Claude Desktop
```
