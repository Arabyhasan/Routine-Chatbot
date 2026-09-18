from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from chatbot import RoutineChatbot
from service_config import ServiceConfig

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Routine Agent</title>
    <style>
        :root {
            --bg: #0f172a;
            --panel: #111827;
            --panel-soft: #1f2937;
            --text: #e5e7eb;
            --muted: #9ca3af;
            --accent: #38bdf8;
            --accent-strong: #0ea5e9;
            --user: #1d4ed8;
            --bot: #374151;
            --border: rgba(148, 163, 184, 0.25);
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: linear-gradient(180deg, #020817, #111827 30%, #0f172a);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .chat-shell {
            width: min(900px, 92vw);
            height: min(88vh, 760px);
            display: flex;
            flex-direction: column;
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid var(--border);
            border-radius: 18px;
            overflow: hidden;
            box-shadow: 0 25px 60px rgba(0,0,0,0.45);
        }
        .header {
            background: linear-gradient(180deg, rgba(15, 23, 42, 0.98), rgba(17, 24, 39, 0.92));
            border-bottom: 1px solid var(--border);
            padding: 20px 22px 16px;
            font-size: 1.2rem;
            font-weight: 800;
            letter-spacing: 0.02em;
        }
        .assistant-badge {
            display: inline-block;
            margin-left: 8px;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #bae6fd;
            background: rgba(56, 189, 248, 0.12);
            padding: 4px 8px;
            border-radius: 999px;
            border: 1px solid rgba(56, 189, 248, 0.4);
        }
        .toolbar {
            display: flex;
            gap: 12px;
            align-items: center;
            padding: 12px 18px 0;
            background: rgba(15, 23, 42, 0.95);
            font-size: 0.9rem;
        }
        select {
            background: var(--panel-soft);
            color: var(--text);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 10px 12px;
            font-size: 0.95rem;
        }
        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 18px 18px 16px;
            background: rgba(17, 24, 39, 0.8);
        }
        .message {
            display: flex;
            margin-bottom: 14px;
        }
        .message.user { justify-content: flex-end; }
        .bubble {
            max-width: 75%;
            border-radius: 16px;
            padding: 12px 14px;
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .message.user .bubble {
            background: var(--user);
            border-bottom-right-radius: 4px;
        }
        .message.bot .bubble {
            background: var(--bot);
            border-bottom-left-radius: 4px;
        }
        .composer {
            display: flex;
            gap: 10px;
            padding: 16px 18px;
            border-top: 1px solid var(--border);
            background: rgba(15, 23, 42, 0.95);
        }
        .clear-btn {
            border: 1px solid var(--border);
            background: rgba(31, 41, 55, 0.9);
            color: var(--text);
            border-radius: 12px;
            padding: 14px 16px;
            font-weight: 600;
            cursor: pointer;
        }
        input {
            flex: 1;
            border: 1px solid var(--border);
            background: var(--panel-soft);
            color: var(--text);
            border-radius: 12px;
            padding: 14px 16px;
            font-size: 1rem;
        }
        button {
            border: none;
            border-radius: 12px;
            padding: 14px 18px;
            background: linear-gradient(135deg, var(--accent), var(--accent-strong));
            color: white;
            font-weight: 700;
            cursor: pointer;
        }
        button:hover { filter: brightness(1.05); }
        .status {
            color: var(--muted);
            font-size: 0.85rem;
            padding: 0 18px 10px;
        }
    </style>
</head>
<body>
    <div class="chat-shell">
        <div class="header">Routine Agent <span class="assistant-badge">AI assistant</span></div>
        <div class="toolbar">
            <label for="serviceSelect">Mode:</label>
            <select id="serviceSelect">
                <option value="slack_gmail_calendar">Slack + Gmail + Calendar</option>
                <option value="slack_gmail">Slack + Gmail</option>
                <option value="gmail">Gmail only</option>
                <option value="slack">Slack only</option>
                <option value="calendar">Calendar only</option>
            </select>
        </div>
        <div class="messages" id="messages"></div>
        <div class="status">Try: “send email to test@example.com”, “can we meet at 8pm?”, “show my schedule”, “what do you remember about me?”</div>
        <div class="composer">
            <button class="clear-btn" id="clearButton" type="button">Clear chat</button>
            <input id="messageInput" type="text" placeholder="Type your message..." />
            <button id="sendButton">Send</button>
        </div>
    </div>

    <script>
        const messages = document.getElementById('messages');
        const input = document.getElementById('messageInput');
        const button = document.getElementById('sendButton');
        const clearButton = document.getElementById('clearButton');
        const serviceSelect = document.getElementById('serviceSelect');

        function addMessage(text, sender) {
            const row = document.createElement('div');
            row.className = 'message ' + sender;
            const bubble = document.createElement('div');
            bubble.className = 'bubble';
            bubble.textContent = text;
            row.appendChild(bubble);
            messages.appendChild(row);
            messages.scrollTop = messages.scrollHeight;
        }

        function getWelcomeMessage() {
            return 'Hi! I can help with your routine, general questions, meeting planning, and I remember preferences you tell me about.';
        }

        function clearMessages() {
            messages.innerHTML = '';
            addMessage('Chat cleared. I am ready for the next request.', 'bot');
        }

        async function updateServiceMode() {
            const mode = serviceSelect.value;
            try {
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode })
                });
                const data = await response.json();
                addMessage(data.reply || `Service mode changed to ${mode}.`, 'bot');
            } catch (error) {
                addMessage('Could not update the service mode.', 'bot');
            }
        }

        async function sendMessage() {
            const text = input.value.trim();
            if (!text) return;
            addMessage(text, 'user');
            input.value = '';
            input.focus();

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text })
                });
                const data = await response.json();
                addMessage(data.reply || 'No response from the agent.', 'bot');
            } catch (error) {
                addMessage('The agent is unavailable right now. Please try again.', 'bot');
            }
        }

        button.addEventListener('click', sendMessage);
        clearButton.addEventListener('click', clearMessages);
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                sendMessage();
            }
        });
        serviceSelect.addEventListener('change', updateServiceMode);

        addMessage(getWelcomeMessage(), 'bot');
        input.focus();
    </script>
</body>
</html>
"""


def build_bot(mode: str):
    mode_map = {
        "slack_gmail_calendar": ServiceConfig(enabled_services=["slack", "gmail", "calendar"], slack_enabled=True, gmail_enabled=True, calendar_enabled=True),
        "slack_gmail": ServiceConfig(enabled_services=["slack", "gmail"], slack_enabled=True, gmail_enabled=True, calendar_enabled=False),
        "gmail": ServiceConfig(enabled_services=["gmail"], slack_enabled=False, gmail_enabled=True, calendar_enabled=False),
        "slack": ServiceConfig(enabled_services=["slack"], slack_enabled=True, gmail_enabled=False, calendar_enabled=False),
        "calendar": ServiceConfig(enabled_services=["calendar"], slack_enabled=False, gmail_enabled=False, calendar_enabled=True),
    }
    return RoutineChatbot(service_config=mode_map.get(mode, mode_map["slack_gmail_calendar"]))


bot = build_bot("slack_gmail_calendar")


class ChatHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path.startswith('/index'):
            body = HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == '/api/status':
            status = {
                'slack': 'ready' if bot.service_config.slack_enabled and bool(bot.slack and bot.slack.bot_token) else 'missing',
                'gmail': 'ready' if bot.service_config.gmail_enabled and bool(bot.google and bot.google.creds is not None) else 'missing',
                'calendar': 'ready' if bot.service_config.calendar_enabled and bool(bot.google and bot.google.creds is not None) else 'missing',
            }
            response = json.dumps(status).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        global bot

        if self.path == '/api/config':
            content_length = int(self.headers.get('Content-Length', '0'))
            raw_body = self.rfile.read(content_length)
            try:
                payload = json.loads(raw_body.decode('utf-8'))
            except Exception:
                payload = {}

            mode = str(payload.get('mode', 'slack_gmail_calendar'))
            bot = build_bot(mode)
            response = json.dumps({"reply": f"Service mode updated to {mode}."}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        if self.path != '/api/chat':
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get('Content-Length', '0'))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode('utf-8'))
        except Exception:
            payload = {}

        message = str(payload.get('message', '')).strip()
        reply = bot.respond(message) if message else 'Please enter a message.'

        response = json.dumps({"reply": reply}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        return


def main():
    server = ThreadingHTTPServer(('0.0.0.0', 8000), ChatHandler)
    print('Routine Agent web UI started at http://localhost:8000')
    print('Press Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping web server...')
        server.server_close()


if __name__ == '__main__':
    main()
