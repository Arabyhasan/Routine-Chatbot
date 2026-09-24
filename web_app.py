from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from chatbot import RoutineChatbot
from service_config import ServiceConfig

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Routine Agent</title>
    <style>
        :root {
            --bg: #0f172a; --panel: #111827; --panel-soft: #1f2937;
            --text: #e5e7eb; --muted: #9ca3af; --accent: #38bdf8;
            --accent-strong: #0ea5e9; --user: #1d4ed8; --bot: #374151;
            --border: rgba(148,163,184,0.25); --success: #22c55e; --warn: #f59e0b;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: system-ui, Arial, sans-serif;
            background: linear-gradient(180deg,#020817,#111827 30%,#0f172a);
            color: var(--text); min-height: 100vh;
            display: flex; align-items: center; justify-content: center;
        }
        .shell {
            width: min(900px,94vw); height: min(88vh,780px);
            display: flex; flex-direction: column;
            background: rgba(15,23,42,0.92);
            border: 1px solid var(--border); border-radius: 18px;
            overflow: hidden; box-shadow: 0 25px 60px rgba(0,0,0,0.45);
        }
        .header {
            background: linear-gradient(180deg,rgba(15,23,42,0.98),rgba(17,24,39,0.92));
            border-bottom: 1px solid var(--border);
            padding: 18px 22px 14px;
            display: flex; align-items: center; gap: 10px;
        }
        .header-title { font-size: 1.15rem; font-weight: 800; letter-spacing: .02em; }
        .badge {
            font-size: .68rem; font-weight: 700; letter-spacing: .08em;
            text-transform: uppercase; color: #bae6fd;
            background: rgba(56,189,248,.12); padding: 3px 8px;
            border-radius: 999px; border: 1px solid rgba(56,189,248,.4);
        }
        .toolbar {
            display: flex; gap: 10px; align-items: center;
            padding: 10px 18px 0;
            background: rgba(15,23,42,0.95); font-size: .9rem;
        }
        select {
            background: var(--panel-soft); color: var(--text);
            border: 1px solid var(--border); border-radius: 10px;
            padding: 8px 12px; font-size: .92rem; cursor: pointer;
        }
        .status-dot {
            width: 8px; height: 8px; border-radius: 50%;
            display: inline-block; margin-right: 4px;
        }
        .dot-ok { background: var(--success); }
        .dot-warn { background: var(--warn); }
        .messages {
            flex: 1; overflow-y: auto; padding: 16px 18px;
            background: rgba(17,24,39,0.8); scroll-behavior: smooth;
        }
        .message { display: flex; margin-bottom: 12px; }
        .message.user { justify-content: flex-end; }
        .bubble {
            max-width: 78%; border-radius: 16px; padding: 11px 14px;
            line-height: 1.55; white-space: pre-wrap; word-break: break-word;
            font-size: .95rem;
        }
        .message.user .bubble { background: var(--user); border-bottom-right-radius: 4px; }
        .message.bot  .bubble { background: var(--bot);  border-bottom-left-radius: 4px; }
        .message.bot.thinking .bubble { opacity: .6; font-style: italic; }
        .hints {
            color: var(--muted); font-size: .82rem;
            padding: 6px 18px 4px; border-top: 1px solid var(--border);
            background: rgba(15,23,42,0.95);
        }
        .composer {
            display: flex; gap: 10px; padding: 14px 18px;
            border-top: 1px solid var(--border); background: rgba(15,23,42,0.95);
        }
        .clear-btn {
            border: 1px solid var(--border); background: rgba(31,41,55,0.9);
            color: var(--text); border-radius: 12px; padding: 12px 14px;
            font-weight: 600; cursor: pointer; white-space: nowrap;
        }
        .clear-btn:hover { background: rgba(55,65,81,0.9); }
        input {
            flex: 1; border: 1px solid var(--border); background: var(--panel-soft);
            color: var(--text); border-radius: 12px; padding: 12px 16px;
            font-size: .97rem; outline: none;
        }
        input:focus { border-color: var(--accent); }
        button#sendButton {
            border: none; border-radius: 12px; padding: 12px 20px;
            background: linear-gradient(135deg,var(--accent),var(--accent-strong));
            color: white; font-weight: 700; cursor: pointer; white-space: nowrap;
        }
        button#sendButton:hover { filter: brightness(1.08); }
        button#sendButton:disabled { opacity: .5; cursor: not-allowed; }
        .sheet-btn {
            border: 1px solid var(--border); background: rgba(31,41,55,0.9);
            color: var(--text); border-radius: 10px; padding: 8px 12px;
            font-size: .85rem; cursor: pointer; white-space: nowrap;
        }
        .sheet-btn:hover { background: rgba(55,65,81,0.9); }
        .sheet-link {
            color: var(--accent); font-size: .85rem; text-decoration: none;
            white-space: nowrap; padding: 8px 4px;
        }
        .sheet-link:hover { text-decoration: underline; }
    </style>
</head>
<body>
<div class="shell">
    <div class="header">
        <span class="header-title">Routine Agent</span>
        <span class="badge">Claude AI</span>
        <span id="apiStatus" style="margin-left:auto;font-size:.8rem;color:var(--muted)"></span>
    </div>
    <div class="toolbar">
        <label for="serviceSelect">Mode:</label>
        <select id="serviceSelect">
            <option value="slack_gmail_calendar">Slack + Gmail + Calendar</option>
            <option value="slack_gmail">Slack + Gmail</option>
            <option value="gmail">Gmail only</option>
            <option value="slack">Slack only</option>
            <option value="calendar">Calendar only</option>
        </select>
        <button class="sheet-btn" id="sheetSyncBtn" type="button">📊 Sync Sheet</button>
        <a class="sheet-link" id="sheetLink" href="#" target="_blank" style="display:none">Open Sheet ↗</a>
    </div>
    <div class="messages" id="messages"></div>
    <div class="hints">
        Try: "show my schedule" · "when am I free today?" · "can we meet at 8pm?" · "send email to x@y.com" · "add gym every weekday at 8pm"
    </div>
    <div class="composer">
        <button class="clear-btn" id="clearButton" type="button">Clear</button>
        <input id="messageInput" type="text" placeholder="Ask anything about your schedule…" autocomplete="off" />
        <button id="sendButton">Send</button>
    </div>
</div>

<script>
    const messages  = document.getElementById('messages');
    const input     = document.getElementById('messageInput');
    const sendBtn   = document.getElementById('sendButton');
    const clearBtn  = document.getElementById('clearButton');
    const svcSelect = document.getElementById('serviceSelect');
    const apiStatus = document.getElementById('apiStatus');

    function addMessage(text, sender, thinking = false) {
        const row  = document.createElement('div');
        row.className = 'message ' + sender + (thinking ? ' thinking' : '');
        const bbl  = document.createElement('div');
        bbl.className = 'bubble';
        bbl.textContent = text;
        row.appendChild(bbl);
        messages.appendChild(row);
        messages.scrollTop = messages.scrollHeight;
        return bbl;  // return so we can update it
    }

    async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;
        addMessage(text, 'user');
        input.value = '';
        sendBtn.disabled = true;

        const thinkBbl = addMessage('Thinking…', 'bot', true);

        try {
            const res  = await fetch('/api/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: text})
            });
            const data = await res.json();
            thinkBbl.parentElement.classList.remove('thinking');
            thinkBbl.textContent = data.reply || 'No response from agent.';
        } catch (err) {
            thinkBbl.parentElement.classList.remove('thinking');
            thinkBbl.textContent = 'Agent unavailable — check the server is running.';
        }
        messages.scrollTop = messages.scrollHeight;
        sendBtn.disabled = false;
        input.focus();
    }

    async function clearChat() {
        messages.innerHTML = '';
        try { await fetch('/api/clear', {method: 'POST'}); } catch {}
        addMessage('Conversation cleared. Ready for your next question!', 'bot');
    }

    async function updateMode() {
        const mode = svcSelect.value;
        try {
            const res  = await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mode})
            });
            const data = await res.json();
            addMessage(data.reply || `Mode changed to ${mode}.`, 'bot');
        } catch {}
    }

    async function checkStatus() {
        try {
            const res  = await fetch('/api/status');
            const data = await res.json();
            const parts = [];
            if (data.claude === 'ok')      parts.push('Claude ✓');
            if (data.slack === 'ready')    parts.push('Slack ✓');
            if (data.gmail === 'ready')    parts.push('Gmail ✓');
            if (data.calendar === 'ready') parts.push('Calendar ✓');
            apiStatus.textContent = parts.join(' · ');
        } catch {}
    }

    sendBtn.addEventListener('click', sendMessage);
    clearBtn.addEventListener('click', clearChat);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(); });
    svcSelect.addEventListener('change', updateMode);

    async function syncSheet() {
        const btn = document.getElementById('sheetSyncBtn');
        btn.textContent = '⏳ Syncing…';
        btn.disabled = true;
        try {
            const res  = await fetch('/api/sheet-sync', {method: 'POST'});
            const data = await res.json();
            if (data.url) {
                const link = document.getElementById('sheetLink');
                link.href = data.url;
                link.style.display = 'inline';
                addMessage('📊 Sheet updated — ' + data.url, 'bot');
            } else {
                addMessage(data.error || 'Sheet sync failed.', 'bot');
            }
        } catch { addMessage('Sheet sync unavailable.', 'bot'); }
        btn.textContent = '📊 Sync Sheet';
        btn.disabled = false;
    }

    document.getElementById('sheetSyncBtn').addEventListener('click', syncSheet);

    // Restore sheet link if available from previous sync
    (async () => {
        try {
            const res = await fetch('/api/sheet-url');
            const data = await res.json();
            if (data.url) {
                const link = document.getElementById('sheetLink');
                link.href = data.url;
                link.style.display = 'inline';
            }
        } catch {}
    })();

    addMessage('Hi! I can help with your schedule, meetings, Slack messages, and emails. What can I do for you?', 'bot');
    input.focus();
    checkStatus();
</script>
</body>
</html>"""


def _build_bot(mode: str) -> RoutineChatbot:
    mode_map = {
        "slack_gmail_calendar": ServiceConfig(enabled_services=["slack","gmail","calendar"], slack_enabled=True,  gmail_enabled=True,  calendar_enabled=True),
        "slack_gmail":          ServiceConfig(enabled_services=["slack","gmail"],            slack_enabled=True,  gmail_enabled=True,  calendar_enabled=False),
        "gmail":                ServiceConfig(enabled_services=["gmail"],                    slack_enabled=False, gmail_enabled=True,  calendar_enabled=False),
        "slack":                ServiceConfig(enabled_services=["slack"],                    slack_enabled=True,  gmail_enabled=False, calendar_enabled=False),
        "calendar":             ServiceConfig(enabled_services=["calendar"],                 slack_enabled=False, gmail_enabled=False, calendar_enabled=True),
    }
    return RoutineChatbot(service_config=mode_map.get(mode, mode_map["slack_gmail_calendar"]))


bot = _build_bot("slack_gmail_calendar")


class ChatHandler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global bot
        if self.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/status":
            import os
            self._send_json(200, {
                "claude":    "ok"      if os.getenv("ANTHROPIC_API_KEY") else "missing",
                "slack":     "ready"   if (bot.service_config.slack_enabled    and bot.slack    and bot.slack.bot_token)        else "missing",
                "gmail":     "ready"   if (bot.service_config.gmail_enabled    and bot.google   and bot.google.creds is not None) else "missing",
                "calendar":  "ready"   if (bot.service_config.calendar_enabled and bot.google   and bot.google.creds is not None) else "missing",
                "sheets":    "ready"   if (bot.google and bot.google.creds is not None) else "missing",
            })
            return

        if self.path == "/api/sheet-url":
            try:
                from sheets_integration import STATE_FILE
                import json as _json
                with open(STATE_FILE) as f:
                    state = _json.load(f)
                self._send_json(200, {"url": state.get("sheet_url", "")})
            except Exception:
                self._send_json(200, {"url": ""})
            return

        self.send_response(404); self.end_headers()

    def do_POST(self):
        global bot
        length  = int(self.headers.get("Content-Length", 0))
        raw     = self.rfile.read(length)
        try:    payload = json.loads(raw.decode())
        except: payload = {}

        if self.path == "/api/config":
            mode = str(payload.get("mode", "slack_gmail_calendar"))
            bot = _build_bot(mode)
            self._send_json(200, {"reply": f"Service mode updated to {mode}."})
            return

        if self.path == "/api/clear":
            bot.clear_history()
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/chat":
            msg = str(payload.get("message", "")).strip()
            reply = bot.respond(msg) if msg else "Please enter a message."
            self._send_json(200, {"reply": reply})
            return

        if self.path == "/api/sheet-sync":
            if bot.google and bot.google.creds:
                try:
                    si = bot.google.get_sheets_integration()
                    url = si.sync(bot.tool_ctx.routine_path)
                    bot.tool_ctx.sheets_url = url
                    self._send_json(200, {"url": url})
                except Exception as exc:
                    self._send_json(200, {"error": str(exc)})
            else:
                self._send_json(200, {"error": "Google not connected — add credentials.json and run: python google_integration.py"})
            return

        self.send_response(404); self.end_headers()

    def log_message(self, *_):
        pass  # suppress access logs


def main():
    import threading
    import webbrowser

    server = ThreadingHTTPServer(("0.0.0.0", 8000), ChatHandler)
    print("Routine Agent → http://localhost:8000")
    print("Press Ctrl+C to stop.")

    # Auto-open the browser shortly after the server starts listening.
    # Needed once the exe is built with --windowed (no console to read
    # the URL from), and harmless for normal `python web_app.py` runs.
    threading.Timer(1.0, lambda: webbrowser.open("http://localhost:8000")).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
