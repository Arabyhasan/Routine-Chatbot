from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Iterator


class RoutineFileLock:
    """Simple file-based lock to avoid concurrent routine writes and double-booking."""

    def __init__(self, lock_path: str = "automation.lock"):
        self.lock_path = lock_path
        self._handle = None

    def acquire(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while True:
            try:
                self._handle = open(self.lock_path, "x")
                return True
            except FileExistsError:
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
            raise TimeoutError(f"Could not acquire routine lock: {self.lock_path}")
        try:
            yield
        finally:
            self.release()
