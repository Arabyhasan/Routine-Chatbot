from __future__ import annotations

import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import account_manager
from mcp_agent_session import AgentSession

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
        .logout-btn {
            border: 1px solid var(--border); background: transparent;
            color: var(--muted); border-radius: 8px; padding: 6px 10px;
            font-size: .78rem; cursor: pointer;
        }
        .logout-btn:hover { color: var(--text); border-color: var(--muted); }

        /* ── Auth gate ─────────────────────────────────────────── */
        .authcard {
            width: min(420px,92vw); background: rgba(15,23,42,0.92);
            border: 1px solid var(--border); border-radius: 18px;
            padding: 32px 28px; box-shadow: 0 25px 60px rgba(0,0,0,0.45);
        }
        .authcard h1 { font-size: 1.3rem; margin-bottom: 6px; }
        .authcard .sub { color: var(--muted); font-size: .88rem; margin-bottom: 22px; }
        .authcard label { display: block; font-size: .8rem; color: var(--muted); margin: 14px 0 6px; }
        .authcard input {
            width: 100%; background: var(--panel-soft); border: 1px solid var(--border);
            color: var(--text); border-radius: 10px; padding: 11px 13px; font-size: .93rem;
        }
        .authcard input:focus { outline: none; border-color: var(--accent); }
        .authbtn {
            width: 100%; margin-top: 20px; border: none; border-radius: 10px;
            padding: 12px; background: linear-gradient(135deg,var(--accent),var(--accent-strong));
            color: white; font-weight: 700; cursor: pointer; font-size: .95rem;
        }
        .authbtn:disabled { opacity: .55; cursor: default; }
        .authswitch { text-align: center; margin-top: 16px; font-size: .85rem; color: var(--muted); }
        .authswitch a { color: var(--accent); cursor: pointer; text-decoration: none; }
        .autherr { color: #fca5a5; font-size: .82rem; margin-top: 10px; min-height: 1.2em; }
        .profile-pick { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 6px; }
        .profile-chip {
            border: 1px solid var(--border); background: var(--panel-soft); color: var(--text);
            border-radius: 20px; padding: 7px 14px; font-size: .85rem; cursor: pointer;
        }
        .profile-chip.active { border-color: var(--accent); color: var(--accent); }

        /* ── Onboarding (post-login, pre-chat) ─────────────────── */
        .onb-step { display: flex; flex-direction: column; gap: 10px; margin-top: 18px; }
        .onb-row {
            display: flex; align-items: center; justify-content: space-between;
            border: 1px solid var(--border); border-radius: 12px; padding: 13px 15px;
            background: var(--panel-soft);
        }
        .onb-row .label { font-size: .9rem; }
        .onb-row .sub { font-size: .76rem; color: var(--muted); }
        .onb-btn {
            border: 1px solid var(--border); background: rgba(56,189,248,.12);
            color: var(--accent); border-radius: 8px; padding: 8px 14px;
            font-size: .82rem; font-weight: 600; cursor: pointer; white-space: nowrap;
        }
        .onb-btn.done { background: rgba(34,197,94,.12); color: var(--success); border-color: rgba(34,197,94,.4); cursor: default; }
        .onb-btn.skip { background: transparent; color: var(--muted); }
        .onb-continue { margin-top: 18px; }
    </style>
</head>
<body>

<!-- ═══════════════ AUTH GATE (login / signup) ═══════════════ -->
<div class="authcard" id="authGate">
    <h1 id="authTitle">Welcome back</h1>
    <div class="sub" id="authSub">Sign in to your Routine Agent profile.</div>

    <div class="profile-pick" id="profilePick"></div>

    <label for="authUser">Name</label>
    <input id="authUser" type="text" autocomplete="username" placeholder="e.g. araby" />
    <label for="authPass">Password</label>
    <input id="authPass" type="password" autocomplete="current-password" placeholder="••••••••" />

    <button class="authbtn" id="authSubmit">Sign in</button>
    <div class="autherr" id="authErr"></div>
    <div class="authswitch" id="authSwitch">New here? <a id="toSignup">Create a profile</a></div>
</div>

<!-- ═══════════════ ONBOARDING (connect Google/Slack) ═══════════════ -->
<div class="authcard" id="onboardGate" style="display:none;">
    <h1>Almost there</h1>
    <div class="sub">Connect the accounts Routine Agent should act on. You can skip any of these and connect them later.</div>
    <div class="onb-step">
        <div class="onb-row">
            <div><div class="label">Google</div><div class="sub">Gmail, Calendar, Sheets</div></div>
            <button class="onb-btn" id="connectGoogleBtn">Connect</button>
        </div>
        <div class="onb-row">
            <div><div class="label">Slack</div><div class="sub">Official Slack MCP server</div></div>
            <button class="onb-btn" id="connectSlackBtn">Connect</button>
        </div>
        <div class="onb-row">
            <div><div class="label">Routine sheet</div><div class="sub">Auto-created or resumed on your Google Drive once connected</div></div>
            <span class="sub">Automatic</span>
        </div>
    </div>
    <button class="authbtn onb-continue" id="onboardContinue">Continue to chat</button>
</div>

<!-- ═══════════════ MAIN CHAT SHELL ═══════════════ -->
<div class="shell" id="chatShell" style="display:none;">
    <div class="header">
        <span class="header-title">Routine Agent</span>
        <span class="badge">Claude AI</span>
        <span id="whoAmI" style="margin-left:12px;font-size:.8rem;color:var(--muted)"></span>
        <span id="apiStatus" style="margin-left:auto;font-size:.8rem;color:var(--muted)"></span>
        <button class="logout-btn" id="logoutBtn" style="margin-left:10px;">Sign out</button>
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
    // ─── Auth gate ──────────────────────────────────────────────
    const authGate    = document.getElementById('authGate');
    const onboardGate = document.getElementById('onboardGate');
    const chatShell   = document.getElementById('chatShell');
    const authTitle   = document.getElementById('authTitle');
    const authSub     = document.getElementById('authSub');
    const authUser    = document.getElementById('authUser');
    const authPass    = document.getElementById('authPass');
    const authSubmit  = document.getElementById('authSubmit');
    const authErr     = document.getElementById('authErr');
    const authSwitch  = document.getElementById('authSwitch');
    const toSignup    = document.getElementById('toSignup');
    const profilePick = document.getElementById('profilePick');
    let mode = 'login'; // or 'signup'

    function setMode(next) {
        mode = next;
        authErr.textContent = '';
        if (mode === 'signup') {
            authTitle.textContent = 'Create your profile';
            authSub.textContent = 'Pick a name and a password — this password only protects your saved logins on this device.';
            authSubmit.textContent = 'Create profile';
            authPass.autocomplete = 'new-password';
            authSwitch.innerHTML = 'Already have a profile? <a id="toLogin">Sign in</a>';
            document.getElementById('toLogin').addEventListener('click', () => setMode('login'));
        } else {
            authTitle.textContent = 'Welcome back';
            authSub.textContent = 'Sign in to your Routine Agent profile.';
            authSubmit.textContent = 'Sign in';
            authPass.autocomplete = 'current-password';
            authSwitch.innerHTML = 'New here? <a id="toSignup">Create a profile</a>';
            document.getElementById('toSignup').addEventListener('click', () => setMode('signup'));
        }
    }
    toSignup.addEventListener('click', () => setMode('signup'));

    async function loadProfiles() {
        try {
            const res = await fetch('/api/profiles');
            const data = await res.json();
            profilePick.innerHTML = '';
            (data.profiles || []).forEach(name => {
                const chip = document.createElement('div');
                chip.className = 'profile-chip';
                chip.textContent = name;
                chip.onclick = () => { authUser.value = name; authPass.focus(); };
                profilePick.appendChild(chip);
            });
        } catch {}
    }

    authSubmit.addEventListener('click', async () => {
        const username = authUser.value.trim();
        const password = authPass.value;
        if (!username || !password) { authErr.textContent = 'Enter a name and password.'; return; }
        authSubmit.disabled = true;
        authErr.textContent = '';
        try {
            const res = await fetch(mode === 'signup' ? '/api/signup' : '/api/login', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, password})
            });
            const data = await res.json();
            if (!data.ok) { authErr.textContent = data.error || 'Something went wrong.'; authSubmit.disabled = false; return; }
            authGate.style.display = 'none';
            enterOnboarding(data);
        } catch {
            authErr.textContent = 'Could not reach the app. Is it still running?';
            authSubmit.disabled = false;
        }
    });
    authPass.addEventListener('keydown', e => { if (e.key === 'Enter') authSubmit.click(); });

    // ─── Onboarding ─────────────────────────────────────────────
    function enterOnboarding(status) {
        onboardGate.style.display = 'block';
        if (status.google_connected) markDone('connectGoogleBtn');
        if (status.slack_connected)  markDone('connectSlackBtn');
    }
    function markDone(id) {
        const btn = document.getElementById(id);
        btn.textContent = 'Connected ✓';
        btn.classList.add('done');
        btn.disabled = true;
    }
    async function connectService(endpoint, btnId) {
        const btn = document.getElementById(btnId);
        btn.textContent = 'Opening browser…';
        btn.disabled = true;
        try {
            const res = await fetch(endpoint, {method: 'POST'});
            const data = await res.json();
            if (data.ok) { markDone(btnId); }
            else { btn.textContent = 'Retry'; btn.disabled = false; alert(data.error || 'Connection failed.'); }
        } catch {
            btn.textContent = 'Retry'; btn.disabled = false;
            alert('Could not reach the app.');
        }
    }
    document.getElementById('connectGoogleBtn').addEventListener('click',
        () => connectService('/api/connect-google', 'connectGoogleBtn'));
    document.getElementById('connectSlackBtn').addEventListener('click',
        () => connectService('/api/connect-slack', 'connectSlackBtn'));
    document.getElementById('onboardContinue').addEventListener('click', () => {
        onboardGate.style.display = 'none';
        chatShell.style.display = 'flex';
        enterChat();
    });

    // ─── Chat (unchanged behaviour, now gated behind login) ───────
    const messages  = document.getElementById('messages');
    const input     = document.getElementById('messageInput');
    const sendBtn   = document.getElementById('sendButton');
    const clearBtn  = document.getElementById('clearButton');
    const svcSelect = document.getElementById('serviceSelect');
    const apiStatus = document.getElementById('apiStatus');
    const whoAmI    = document.getElementById('whoAmI');
    const logoutBtn = document.getElementById('logoutBtn');

    function addMessage(text, sender, thinking = false) {
        const row  = document.createElement('div');
        row.className = 'message ' + sender + (thinking ? ' thinking' : '');
        const bbl  = document.createElement('div');
        bbl.className = 'bubble';
        bbl.textContent = text;
        row.appendChild(bbl);
        messages.appendChild(row);
        messages.scrollTop = messages.scrollHeight;
        return bbl;
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
                method: 'POST', headers: {'Content-Type': 'application/json'},
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
        const svcmode = svcSelect.value;
        try {
            const res  = await fetch('/api/config', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mode: svcmode})
            });
            const data = await res.json();
            addMessage(data.reply || `Mode changed to ${svcmode}.`, 'bot');
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

    logoutBtn.addEventListener('click', async () => {
        try { await fetch('/api/logout', {method: 'POST'}); } catch {}
        location.reload();
    });

    function enterChat() {
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
        (async () => {
            try {
                const res = await fetch('/api/whoami');
                const data = await res.json();
                whoAmI.textContent = data.username ? ('· ' + data.username) : '';
            } catch {}
        })();
        addMessage('Hi! I can help with your schedule, meetings, Slack messages, and emails. What can I do for you?', 'bot');
        input.focus();
        checkStatus();
    }

    // ─── Boot: check if a session is already active (e.g. page refresh) ──
    (async () => {
        try {
            const res = await fetch('/api/whoami');
            const data = await res.json();
            if (data.username) {
                chatShell.style.display = 'flex';
                enterChat();
                return;
            }
        } catch {}
        loadProfiles();
        setMode('login');
    })();
</script>
</body>
</html>"""


# ─── Session (single active profile at a time — this is a local desktop app) ──

session = {"username": None, "vault": None, "password": None}
agent_session: Optional[AgentSession] = None


def _profile_paths(username: str) -> dict:
    d = account_manager.profile_dir(username)
    d.mkdir(parents=True, exist_ok=True)
    return {
        "routine": str(d / "routine.json"),
        "google_token": str(d / "token.json"),
        "slack_token": d / "slack_token.json",
    }


def _materialize_vault_to_disk(username: str, vault: account_manager.Vault) -> dict:
    """Write out this profile's saved tokens as plaintext files, only for the
    duration of this session, so google_integration.py / slack_mcp_auth.py can
    keep working exactly as they already do. The encrypted vault stays the
    source of truth; these are just a transient working copy."""
    paths = _profile_paths(username)
    if vault.google_token:
        Path(paths["google_token"]).write_text(vault.google_token)
    if vault.slack_token:
        paths["slack_token"].write_text(vault.slack_token)
    return paths


MODE_FLAGS = {
    "slack_gmail_calendar": {"ENABLE_SLACK": "true",  "ENABLE_GMAIL": "true",  "ENABLE_CALENDAR": "true"},
    "slack_gmail":          {"ENABLE_SLACK": "true",  "ENABLE_GMAIL": "true",  "ENABLE_CALENDAR": "false"},
    "gmail":                {"ENABLE_SLACK": "false", "ENABLE_GMAIL": "true",  "ENABLE_CALENDAR": "false"},
    "slack":                {"ENABLE_SLACK": "true",  "ENABLE_GMAIL": "false", "ENABLE_CALENDAR": "false"},
    "calendar":             {"ENABLE_SLACK": "false", "ENABLE_GMAIL": "false", "ENABLE_CALENDAR": "true"},
}


def _start_session_for(username: str, mode: str = "slack_gmail_calendar") -> AgentSession:
    """Build and start a real AgentSession (spawns mcp_server.py, connects
    Slack's official server if this profile has it), scoped to one profile's
    own routine/knowledge/token files."""
    paths = _profile_paths(username)
    vault = session["vault"]
    s = AgentSession(
        routine_path=paths["routine"],
        google_token_path=paths["google_token"] if (vault and vault.google_token) else paths["google_token"],
        knowledge_path=str(account_manager.profile_dir(username) / "knowledge_store.json"),
        slack_token_path=str(paths["slack_token"]) if (vault and vault.slack_token) else None,
        service_env=MODE_FLAGS.get(mode, MODE_FLAGS["slack_gmail_calendar"]),
    )
    s.start()
    return s


class ChatHandler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode())
        except Exception:
            return {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/profiles":
            self._send_json(200, {"profiles": account_manager.list_profiles()})
            return

        if self.path == "/api/whoami":
            self._send_json(200, {"username": session["username"]})
            return

        if self.path == "/api/status":
            vault = session.get("vault")
            self._send_json(200, {
                "claude":    "ok"    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY") else "missing",
                "slack":     "ready" if (vault and vault.slack_token) else "missing",
                "gmail":     "ready" if (vault and vault.google_token) else "missing",
                "calendar":  "ready" if (vault and vault.google_token) else "missing",
                "sheets":    "ready" if (vault and vault.google_token) else "missing",
            })
            return

        if self.path == "/api/sheet-url":
            try:
                from sheets_integration import STATE_FILE
                with open(STATE_FILE) as f:
                    state = json.load(f)
                self._send_json(200, {"url": state.get("sheet_url", "")})
            except Exception:
                self._send_json(200, {"url": ""})
            return

        self.send_response(404); self.end_headers()

    def do_POST(self):
        global agent_session
        payload = self._read_json()

        # ── Auth ──────────────────────────────────────────────
        if self.path == "/api/signup":
            username, password = str(payload.get("username", "")).strip(), str(payload.get("password", ""))
            try:
                vault = account_manager.create_profile(username, password)
            except account_manager.ProfileAlreadyExists:
                self._send_json(200, {"ok": False, "error": "That name is already taken. Try signing in instead."})
                return
            except ValueError as exc:
                self._send_json(200, {"ok": False, "error": str(exc)})
                return
            session["username"], session["vault"], session["password"] = username, vault, password
            agent_session = _start_session_for(username)
            self._send_json(200, {"ok": True, "google_connected": False, "slack_connected": False})
            return

        if self.path == "/api/login":
            username, password = str(payload.get("username", "")).strip(), str(payload.get("password", ""))
            try:
                vault = account_manager.login(username, password)
            except account_manager.InvalidCredentials as exc:
                self._send_json(200, {"ok": False, "error": str(exc)})
                return
            session["username"], session["vault"], session["password"] = username, vault, password
            _materialize_vault_to_disk(username, vault)
            agent_session = _start_session_for(username)
            self._send_json(200, {
                "ok": True,
                "google_connected": bool(vault.google_token),
                "slack_connected": bool(vault.slack_token),
            })
            return

        if self.path == "/api/logout":
            if agent_session:
                agent_session.stop()
            # Remove the transient plaintext token copies — only the encrypted
            # vault should survive between sessions.
            if session["username"]:
                paths = _profile_paths(session["username"])
                for p in (paths["google_token"], paths["slack_token"]):
                    try:
                        Path(p).unlink(missing_ok=True)
                    except Exception:
                        pass
            session["username"], session["vault"], session["password"] = None, None, None
            agent_session = None
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/connect-google":
            if not session["username"]:
                self._send_json(200, {"ok": False, "error": "Not signed in."})
                return
            paths = _profile_paths(session["username"])
            try:
                from google_integration import GoogleIntegration
                gi = GoogleIntegration(credentials_path="credentials.json", token_path=paths["google_token"])
                if gi.creds is None:
                    self._send_json(200, {"ok": False, "error": "credentials.json not found. Add it to the app folder first (see Google Cloud setup steps)."})
                    return
                token_json = Path(paths["google_token"]).read_text()
                session["vault"].google_token = token_json
                account_manager.save_vault(session["username"], session["password"], session["vault"])
                # No restart needed: mcp_server.py re-reads the token file fresh
                # on every tool call, and it was already pointed at this exact
                # path when the session started.
            except Exception as exc:
                self._send_json(200, {"ok": False, "error": str(exc)})
                return
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/connect-slack":
            if not session["username"]:
                self._send_json(200, {"ok": False, "error": "Not signed in."})
                return
            if os.getenv("ENABLE_SLACK_MCP", "").lower() not in ("1", "true", "yes"):
                self._send_json(200, {"ok": False, "error": "Slack MCP is not enabled. Set ENABLE_SLACK_MCP=true in .env first."})
                return
            paths = _profile_paths(session["username"])
            try:
                from slack_mcp_auth import build_slack_http_client
                http_client = asyncio.run(build_slack_http_client(token_path=paths["slack_token"]))
                if not http_client:
                    self._send_json(200, {"ok": False, "error": "Slack connection was cancelled or failed."})
                    return
                if paths["slack_token"].exists():
                    session["vault"].slack_token = paths["slack_token"].read_text()
                    account_manager.save_vault(session["username"], session["password"], session["vault"])
                # Unlike Google, Slack's remote connection is established once
                # at session start — restart so the now-saved token actually
                # gets used to open the Slack MCP connection this time.
                if agent_session:
                    agent_session.stop()
                agent_session = _start_session_for(session["username"])
            except Exception as exc:
                self._send_json(200, {"ok": False, "error": str(exc)})
                return
            self._send_json(200, {"ok": True})
            return

        # ── Chat (requires an active session) ───────────────────
        if not session["username"] or agent_session is None:
            self._send_json(401, {"error": "Not signed in."})
            return

        if self.path == "/api/config":
            mode = str(payload.get("mode", "slack_gmail_calendar"))
            agent_session.stop()
            agent_session = _start_session_for(session["username"], mode=mode)
            self._send_json(200, {"reply": f"Service mode updated to {mode}."})
            return

        if self.path == "/api/clear":
            agent_session.clear_history()
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/chat":
            msg = str(payload.get("message", "")).strip()
            try:
                reply = agent_session.chat(msg) if msg else "Please enter a message."
            except Exception as exc:
                reply = f"Something went wrong reaching the agent: {exc}"
            self._send_json(200, {"reply": reply})
            return

        if self.path == "/api/sheet-sync":
            vault = session.get("vault")
            if vault and vault.google_token:
                try:
                    url = agent_session.sync_sheets()
                    self._send_json(200, {"url": url})
                except Exception as exc:
                    self._send_json(200, {"error": str(exc)})
            else:
                self._send_json(200, {"error": "Google not connected — connect it from the onboarding step."})
            return

        self.send_response(404); self.end_headers()

    def log_message(self, *_):
        pass  # suppress access logs


def _make_console_utf8_safe() -> None:
    """
    BUG FIX: Windows' console defaults to cp1252, which can't encode
    characters like the arrow used below — this crashed with
    UnicodeEncodeError the moment main() tried to print it. Reconfiguring
    stdout/stderr to UTF-8 (with errors='replace' as a last resort, never
    a crash) fixes this for any text, not just the one line that happened
    to trigger it first.

    Guarded because sys.stdout can be None or a non-reconfigurable object
    when running as a --windowed PyInstaller build with no console at all
    — in that case there's nothing to fix and nothing to crash either.
    """
    import sys
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main():
    import threading
    import webbrowser

    _make_console_utf8_safe()

    server = ThreadingHTTPServer(("0.0.0.0", 8000), ChatHandler)
    print("Routine Agent -> http://localhost:8000")
    print("Press Ctrl+C to stop.")

    threading.Timer(1.0, lambda: webbrowser.open("http://localhost:8000")).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
