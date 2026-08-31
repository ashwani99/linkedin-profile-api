"""
Owns the single LinkedIn session: its cookies, its status, and serialized
access to it. Backed by an encrypted file on disk (see core/security.py),
with an in-memory copy as the source of truth during the process's lifetime
(write-through: every mutation updates memory and persists immediately).

Concurrency model: `lock` is acquired by callers (the /profile route, via
VoyagerClient) for the full duration of a single outbound LinkedIn request.
Because there's exactly one LinkedIn identity, this serializes all traffic
to LinkedIn to one request at a time — see notes.md for why.
"""

import asyncio
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum

from app.config import settings
from app.core.security import InvalidToken, decrypt, encrypt
from app.exceptions import SessionChallengeRequired, SessionNotConnected


class SessionStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    CHALLENGE_REQUIRED = "challenge_required"


@dataclass
class SessionData:
    li_at: str
    jsessionid: str | None
    status: SessionStatus
    connected_at: str  # ISO 8601, set on connect(), unchanged by challenge/disconnect


class SessionManager:
    def __init__(self, store_path: str | None = None):
        self._store_path = store_path or settings.session_store_path
        self._data: SessionData | None = None
        self.lock = asyncio.Lock()
        self._load()

    # --- persistence -------------------------------------------------

    def _load(self) -> None:
        """Populate in-memory state from disk. Any failure to read/decrypt
        (missing file, wrong key, corrupted data) is treated as "no
        session" rather than a startup crash — a fresh deploy or a first
        run legitimately has no session yet."""
        if not os.path.exists(self._store_path):
            self._data = None
            return
        try:
            with open(self._store_path, "rb") as f:
                ciphertext = f.read()
            plaintext = decrypt(ciphertext)
            raw = json.loads(plaintext)
            raw["status"] = SessionStatus(raw["status"])
            self._data = SessionData(**raw)
        except (InvalidToken, json.JSONDecodeError, KeyError, ValueError):
            self._data = None

    def _persist(self) -> None:
        """Atomic write: write to a temp file in the same directory, then
        rename over the target. Avoids a half-written file if the process
        is killed mid-write."""
        assert self._data is not None
        payload = json.dumps(asdict(self._data)).encode()
        ciphertext = encrypt(payload)

        target_dir = os.path.dirname(os.path.abspath(self._store_path)) or "."
        fd, tmp_path = tempfile.mkstemp(dir=target_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(ciphertext)
            os.replace(tmp_path, self._store_path)
        except BaseException:
            os.unlink(tmp_path)
            raise

    # --- mutations -----------------------------------------------------

    async def connect(self, li_at: str, jsessionid: str | None) -> None:
        """Called by POST /auth/connect. Overwrites any existing session."""
        async with self.lock:
            self._data = SessionData(
                li_at=li_at,
                jsessionid=jsessionid,
                status=SessionStatus.CONNECTED,
                connected_at=datetime.now(timezone.utc).isoformat(),
            )
            self._persist()

    async def disconnect(self) -> None:
        """Called by POST /auth/disconnect. Removes the session entirely
        (not just a status flip) so no stale cookie lingers on disk."""
        async with self.lock:
            self._data = None
            if os.path.exists(self._store_path):
                os.remove(self._store_path)

    def mark_challenge_required_locked(self) -> None:
        """Called by VoyagerClient, mid-request, after `lock` is already
        held — this is why it's sync and doesn't acquire the lock itself
        (asyncio.Lock isn't reentrant; re-acquiring here would deadlock)."""
        if self._data is not None:
            self._data.status = SessionStatus.CHALLENGE_REQUIRED
            self._persist()

    # --- reads -----------------------------------------------------------

    def get_status(self) -> dict:
        """Safe to call without the lock — used by GET /auth/status, which
        should stay cheap and never block behind an in-flight profile fetch."""
        if self._data is None:
            return {"status": SessionStatus.DISCONNECTED.value, "connected_at": None}
        return {"status": self._data.status.value, "connected_at": self._data.connected_at}

    def get_cookies(self) -> dict[str, str]:
        """Callers must hold `lock` before calling this (VoyagerClient does,
        for the duration of a request). Raises the appropriate AppError
        subclass rather than returning None/empty, so routes don't need
        their own not-connected checks."""
        if self._data is None:
            raise SessionNotConnected("No LinkedIn session has been connected yet.")
        if self._data.status == SessionStatus.CHALLENGE_REQUIRED:
            raise SessionChallengeRequired(
                "LinkedIn issued a challenge on the last request. "
                "Re-run the local bootstrap script to reconnect."
            )
        cookies = {"li_at": self._data.li_at}
        if self._data.jsessionid:
            cookies["JSESSIONID"] = self._data.jsessionid
        return cookies


# Single shared instance for the app's lifetime.
session_manager = SessionManager()
