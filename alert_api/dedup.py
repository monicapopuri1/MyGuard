import re
import time
import threading
from typing import Tuple

# Same pattern as detector/anpr.py's _PLATE_PATTERN, duplicated rather than
# imported: alert_api and detector ship as separate Docker images (see
# Dockerfile.alert / Dockerfile.detector) with no shared filesystem at runtime.
# Keep this in sync if the plate format in anpr.py ever changes.
_PLATE_PATTERN = re.compile(
    r"^([A-Z]{2}\s?\d{2}\s?[A-Z]{1,2}\s?\d{4}|"   # State format
    r"\d{2}BH\s?\d{4}\s?[A-Z]{1,2})$",              # BH series
    re.IGNORECASE,
)

_MIN_CLEAN_PLATE_LEN = 4


class DedupFilter:
    """
    Prevents repeated WhatsApp alerts for the same vehicle within a configurable
    time window. Thread-safe via a lock (multiple detector workers POST concurrently).

    Dedup key depends on plate quality, since OCR noise on an unclean read
    produces a different garbled string almost every frame, which would
    otherwise defeat a plate-only dedup key:
      - Clean, regex-valid plate -> key = (plate, camera_id, alert_kind). Same
        vehicle keeps suppressing duplicates for as long as it keeps
        reappearing within the window, regardless of exact timing.
      - Empty/garbled plate (OCR noise, "UNREAD") -> key = (camera_id, time_bucket, alert_kind).
        Groups alerts from the same camera within the same window-sized time
        slice, since an unreliable plate read can't be used to tell two
        different vehicles apart.

    alert_kind (e.g. "speeding" vs "wrong_way") is always part of the key, so a
    vehicle already deduped for one kind of alert doesn't silently suppress an
    unrelated, equally important alert for the same vehicle.
    """

    def __init__(self, window_seconds: int = 60):
        self._window = window_seconds
        self._seen: dict[Tuple[str, str, str], float] = {}
        self._lock = threading.Lock()

    def _key(self, plate: str, camera_id: str, alert_kind: str) -> Tuple[str, str, str]:
        cleaned = plate.strip()
        if len(cleaned) > _MIN_CLEAN_PLATE_LEN and _PLATE_PATTERN.fullmatch(cleaned):
            return (cleaned.upper(), camera_id, alert_kind)
        time_bucket = int(time.monotonic() // self._window)
        return (camera_id, str(time_bucket), alert_kind)

    def is_duplicate(self, plate: str, camera_id: str, alert_kind: str = "speeding") -> bool:
        key = self._key(plate, camera_id, alert_kind)
        with self._lock:
            last = self._seen.get(key)
            if last is None:
                return False
            return (time.monotonic() - last) < self._window

    def record(self, plate: str, camera_id: str, alert_kind: str = "speeding"):
        key = self._key(plate, camera_id, alert_kind)
        with self._lock:
            self._seen[key] = time.monotonic()
            self._evict()

    def _evict(self):
        now = time.monotonic()
        stale = [k for k, t in self._seen.items() if now - t > self._window * 2]
        for k in stale:
            del self._seen[k]
