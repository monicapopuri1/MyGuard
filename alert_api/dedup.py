import time
import threading
from typing import Tuple


class DedupFilter:
    """
    Prevents the same plate+camera combination from firing repeated WhatsApp messages
    within a configurable time window.
    Thread-safe via a lock (multiple detector workers POST concurrently).
    """

    def __init__(self, window_seconds: int = 60):
        self._window = window_seconds
        self._seen: dict[Tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def is_duplicate(self, plate: str, camera_id: str) -> bool:
        key = (plate.upper(), camera_id)
        with self._lock:
            last = self._seen.get(key)
            if last is None:
                return False
            return (time.monotonic() - last) < self._window

    def record(self, plate: str, camera_id: str):
        key = (plate.upper(), camera_id)
        with self._lock:
            self._seen[key] = time.monotonic()
            self._evict()

    def _evict(self):
        now = time.monotonic()
        stale = [k for k, t in self._seen.items() if now - t > self._window * 2]
        for k in stale:
            del self._seen[k]
