"""
slack_mcp_auth.py — OAuth wiring for Slack's official, hosted MCP server
(https://mcp.slack.com/mcp), so mcp_client.py can use Slack's own tools
instead of our custom send_slack_message/slack_integration.py.

This is the SAME kind of one-time browser login as Google's OAuth flow in
google_integration.py: the user's browser opens, they approve, and this
module captures the result and stores a token on disk. No bot token, no
Slack app secret to type in .env.

One real prerequisite that only the user (or their Slack workspace admin)
can complete: mcp.slack.com requires a workspace admin to approve the MCP
integration before ANY external client (including this one) can connect.
That approval step happens on Slack's side and can't be done from code.

Usage:
    from slack_mcp_auth import build_slack_http_client
    http_client = await build_slack_http_client()   # None if user cancels/declines
    if http_client:
        servers.append(RemoteServer(url=SLACK_MCP_URL, http_client=http_client, label="slack"))
"""
from __future__ import annotations

import asyncio
import json
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

import httpx2

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

SLACK_MCP_URL = "https://mcp.slack.com/mcp"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8787
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}/callback"
TOKEN_FILE = Path(__file__).resolve().parent / ".slack_mcp_tokens.json"


# ─── Token storage (mirrors what token.json does for Google) ────────────────

class FileTokenStorage(TokenStorage):
    """Persists Slack MCP OAuth tokens + client registration to a local JSON file."""

    def __init__(self, path: Path = TOKEN_FILE):
        self.path = path

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2))

    async def get_tokens(self) -> Optional[OAuthToken]:
        data = self._read().get("tokens")
        return OAuthToken.model_validate(data) if data else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        data = self._read()
        data["tokens"] = tokens.model_dump(mode="json")
        self._write(data)

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        data = self._read().get("client_info")
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        data = self._read()
        data["client_info"] = client_info.model_dump(mode="json")
        self._write(data)


# ─── Local redirect callback server ──────────────────────────────────────────
# Same pattern as Google's InstalledAppFlow.run_local_server(): open the
# user's browser, catch the redirect on a local port, hand the ?code=...
# back to the waiting OAuth flow.

@dataclass
class _CallbackResult:
    code: Optional[str] = None
    state: Optional[str] = None
    error: Optional[str] = None


def _run_callback_server(result_holder: _CallbackResult, ready: threading.Event) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404); self.end_headers(); return
            qs = parse_qs(parsed.query)
            result_holder.code = qs.get("code", [None])[0]
            result_holder.state = qs.get("state", [None])[0]
            result_holder.error = qs.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            body = (
                "<html><body style='font-family:sans-serif;padding:40px;'>"
                "<h2>Slack connected.</h2><p>You can close this tab and go back to Routine Agent.</p>"
                "</body></html>"
                if result_holder.code else
                "<html><body style='font-family:sans-serif;padding:40px;'>"
                "<h2>Slack connection failed or was cancelled.</h2></body></html>"
            )
            self.wfile.write(body.encode())
            threading.Thread(target=server.shutdown, daemon=True).start()

        def log_message(self, *_):
            pass  # keep this quiet, like web_app.py does

    server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler)
    ready.set()
    server.serve_forever()


async def _wait_for_callback() -> _CallbackResult:
    result_holder = _CallbackResult()
    ready = threading.Event()
    thread = threading.Thread(target=_run_callback_server, args=(result_holder, ready), daemon=True)
    thread.start()
    await asyncio.to_thread(ready.wait)   # server socket is bound before we return
    await asyncio.to_thread(thread.join)  # blocks (in a worker thread) until the callback fires
    return result_holder


# ─── Building the OAuth-aware httpx client for streamable_http_client() ────

async def build_slack_http_client() -> Optional["httpx2.AsyncClient"]:
    """
    Runs (or resumes) the Slack MCP OAuth flow and returns an httpx2.AsyncClient
    pre-configured with valid Slack credentials, ready to pass into
    streamable_http_client(SLACK_MCP_URL, http_client=this).

    Returns None if the user's browser flow fails or is cancelled — callers
    should treat that as "Slack tools unavailable this session", not a crash.
    """
    storage = FileTokenStorage()

    async def redirect_handler(url: str) -> None:
        webbrowser.open(url)

    async def callback_handler() -> AuthorizationCodeResult:
        result = await _wait_for_callback()
        if not result.code:
            raise RuntimeError(f"Slack OAuth did not return a code (error={result.error!r})")
        return AuthorizationCodeResult(code=result.code, state=result.state)

    provider = OAuthClientProvider(
        server_url=SLACK_MCP_URL,
        client_metadata=OAuthClientMetadata(
            client_name="Routine Agent",
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="",  # Slack's server determines available scopes during registration
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    try:
        return httpx2.AsyncClient(auth=provider, timeout=30.0)
    except Exception as exc:
        print(f"[slack_mcp_auth] Could not set up Slack OAuth: {exc}")
        return None
