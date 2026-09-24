"""
account_manager.py — local encrypted profiles for Routine Agent.

What this solves: Google/Slack OAuth is real and already works (google_integration.py,
slack_mcp_auth.py) — but by default it stores one token.json / one Slack token
for whoever runs the app. This module adds actual user accounts on top:

  - A profile is created with a username + a local password.
  - The password never leaves this machine and is never sent to Google/Slack —
    it only encrypts/decrypts this profile's saved Google + Slack tokens at rest.
  - On login, the password must correctly decrypt the stored tokens (wrong
    password = decryption fails = rejected). No separate password hash to
    manage or leak.
  - Once logged in, the decrypted Google/Slack tokens are handed to
    google_integration.py / slack_mcp_auth.py so the rest of the app behaves
    exactly as if token.json / the Slack token file existed normally — this
    module is purely the encrypted storage + login layer in front of them.

Multiple people can use the same installed app (same PC, or the same .exe
handed to different clients) without seeing each other's Google/Slack access.

Layout on disk:
    profiles/
      <username>/
        salt.bin        — random salt for this profile's key derivation (not secret)
        vault.enc        — encrypted JSON blob: {"google": <token json or null>,
                                                   "slack": <token json or null>,
                                                   "sheet_id": <linked spreadsheet id or null>}
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
PBKDF2_ITERATIONS = 480_000  # OWASP 2023+ recommended minimum for PBKDF2-HMAC-SHA256


class InvalidCredentials(Exception):
    """Wrong username or password."""


class ProfileAlreadyExists(Exception):
    pass


@dataclass
class Vault:
    google_token: Optional[str] = None   # raw contents of a token.json-equivalent
    slack_token: Optional[str] = None    # raw contents of a Slack MCP token blob
    sheet_id: Optional[str] = None       # linked Google Sheet spreadsheet ID, if any

    def to_json(self) -> str:
        return json.dumps({
            "google_token": self.google_token,
            "slack_token": self.slack_token,
            "sheet_id": self.sheet_id,
        })

    @classmethod
    def from_json(cls, raw: str) -> "Vault":
        data = json.loads(raw)
        return cls(
            google_token=data.get("google_token"),
            slack_token=data.get("slack_token"),
            sheet_id=data.get("sheet_id"),
        )


def profile_dir(username: str) -> Path:
    """Public accessor for a profile's on-disk folder, e.g. for placing a
    per-profile routine.json or transient plaintext token file alongside
    the encrypted vault."""
    return _profile_dir(username)


def _profile_dir(username: str) -> Path:
    safe = "".join(c for c in username.strip().lower() if c.isalnum() or c in "-_")
    if not safe:
        raise ValueError("Username must contain at least one letter, number, - or _")
    return PROFILES_DIR / safe


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def list_profiles() -> list[str]:
    """Usernames of every profile that exists on this machine (for a 'pick your name' login screen)."""
    if not PROFILES_DIR.exists():
        return []
    return sorted(p.name for p in PROFILES_DIR.iterdir() if p.is_dir() and (p / "vault.enc").exists())


def create_profile(username: str, password: str) -> Vault:
    """Create a brand-new, empty profile. Raises ProfileAlreadyExists if the name is taken."""
    if not password:
        raise ValueError("Password cannot be empty")
    d = _profile_dir(username)
    if d.exists():
        raise ProfileAlreadyExists(f"A profile named '{username}' already exists.")
    d.mkdir(parents=True)

    salt = os.urandom(16)
    (d / "salt.bin").write_bytes(salt)

    vault = Vault()
    key = _derive_key(password, salt)
    (d / "vault.enc").write_bytes(Fernet(key).encrypt(vault.to_json().encode("utf-8")))
    return vault


def login(username: str, password: str) -> Vault:
    """Decrypt and return a profile's vault. Raises InvalidCredentials on wrong username/password."""
    d = _profile_dir(username)
    salt_path, vault_path = d / "salt.bin", d / "vault.enc"
    if not salt_path.exists() or not vault_path.exists():
        raise InvalidCredentials("No profile with that name exists.")

    salt = salt_path.read_bytes()
    key = _derive_key(password, salt)
    try:
        raw = Fernet(key).decrypt(vault_path.read_bytes())
    except InvalidToken:
        raise InvalidCredentials("Incorrect password.")
    return Vault.from_json(raw.decode("utf-8"))


def save_vault(username: str, password: str, vault: Vault) -> None:
    """
    Re-encrypt and persist an updated vault (e.g. after connecting Google/Slack,
    or linking a spreadsheet). Requires the password again — this function
    doesn't trust a cached key, so a stolen in-memory session can't silently
    rewrite the vault without the password.
    """
    d = _profile_dir(username)
    salt_path, vault_path = d / "salt.bin", d / "vault.enc"
    if not salt_path.exists():
        raise InvalidCredentials("No profile with that name exists.")
    salt = salt_path.read_bytes()
    key = _derive_key(password, salt)

    # Verify the password is actually correct before overwriting anything.
    try:
        Fernet(key).decrypt(vault_path.read_bytes())
    except InvalidToken:
        raise InvalidCredentials("Incorrect password.")

    vault_path.write_bytes(Fernet(key).encrypt(vault.to_json().encode("utf-8")))


def delete_profile(username: str, password: str) -> None:
    """Permanently remove a profile and its stored tokens. Requires correct password."""
    login(username, password)  # raises InvalidCredentials if wrong, before deleting anything
    d = _profile_dir(username)
    for f in d.iterdir():
        f.unlink()
    d.rmdir()
