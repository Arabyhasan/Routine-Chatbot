from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Iterator

import psutil


class RoutineFileLock:
    """
    File-based lock to avoid concurrent routine writes and double-booking.

    BUG FIX: the original version used a plain "does this file exist" marker
    (open(path, "x")). That works fine for a clean release, but has no way to
    tell a genuinely-held lock apart from one abandoned by a process that
    died without calling release() — which is a NORMAL event here, not an
    edge case: Claude Desktop restarts or kills the MCP server subprocess
    routinely (reinstalling the extension, the app itself restarting,
    crashes). Once that happened once, every future acquire() failed for the
    full timeout, surfacing to the user as a permission/lock error with no
    way to recover except manually finding and deleting the lock file.

    Fix: the lock file now stores the PID of whoever holds it. If a new
    acquire() finds an existing lock file, it checks whether that PID is
    still actually running (psutil.pid_exists — real process-table check,
    not just "the file exists"). If the owning process is dead, the lock is
    stale and gets cleared automatically instead of blocking.
    """

    def __init__(self, lock_path: str = "automation.lock"):
        self.lock_path = lock_path
        self._handle = None

    def _read_owner_pid(self) -> int | None:
        try:
            with open(self.lock_path) as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return None

    def _clear_if_stale(self) -> None:
        owner_pid = self._read_owner_pid()
        # BUG FIX: an unreadable lock (empty or corrupt content) used to be
        # left alone here ("can't tell, do nothing"), which meant a lock file
        # orphaned by a process that crashed between creating the file and
        # writing its PID into it — a real, observed failure mode — could
        # never be cleared and would block every future write forever. If we
        # can't confirm a live owner, the lock can't be trusted, so it gets
        # cleared either way.
        if owner_pid is not None and psutil.pid_exists(owner_pid):
            return  # genuinely still held by a live process — leave it
        try:
            os.remove(self.lock_path)
        except FileNotFoundError:
            pass  # another process already cleared it — fine

    def acquire(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while True:
            self._clear_if_stale()
            try:
                self._handle = open(self.lock_path, "x")
                self._handle.write(str(os.getpid()))
                self._handle.flush()
                return True
            except (FileExistsError, PermissionError):
                # PermissionError (not just FileExistsError) is included
                # because Windows can report a briefly-locked file this way
                # — antivirus, search indexing, or cloud sync (OneDrive etc.)
                # touching the file for a moment — rather than FileExistsError.
                # If the underlying cause isn't transient (e.g. the working
                # directory itself isn't writable), this will still correctly
                # time out and raise a clear TimeoutError instead of hanging.
                if time.time() >= deadline:
                    return False
                time.sleep(0.1)

    def release(self) -> bool:
        if self._handle is None:
            return False
        try:
            self._handle.close()
            os.remove(self.lock_path)
            self._handle = None
            return True
        except FileNotFoundError:
            self._handle = None
            return False

    @contextmanager
    def locked(self, timeout: float = 5.0) -> Iterator[None]:
        acquired = self.acquire(timeout)
        if not acquired:
            raise TimeoutError(
                f"Could not acquire routine lock: {self.lock_path} "
                f"(held by a still-running process — try again shortly)"
            )
        try:
            yield
        finally:
            self.release()
