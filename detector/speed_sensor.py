import time
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("speed_sensor")


@dataclass
class _CrossingRecord:
    vehicle_id: int
    prev_cy: Optional[int] = None
    t_line_a: Optional[float] = None
    t_line_b: Optional[float] = None


@dataclass
class CrossingEvent:
    speed_kmh: float
    wrong_way: bool


class SpeedSensor:
    """
    Virtual two-line speed trap.

    A vehicle is timed between LINE_A and LINE_B.
    Speed = calibration_metres / elapsed_seconds * 3.6  (km/h)

    LINE_A and LINE_B are horizontal pixel rows at fixed Y ratios of the frame height.
    A vehicle "crosses" a line when its centroid Y transitions across that line's Y
    coordinate, in *either* direction — this is what lets the same logic detect both
    normal traffic (A crossed before B) and wrong-way traffic (B crossed before A).
    """

    # Clear stale records after this many seconds (vehicle left frame without completing crossing)
    _STALE_TIMEOUT_S = 10.0

    def __init__(
        self,
        frame_height: int,
        calibration_metres: float,
        line_a_ratio: float,
        line_b_ratio: float,
        max_speed_kmh: float = 80.0,
    ):
        self.line_a_y = int(frame_height * line_a_ratio)
        self.line_b_y = int(frame_height * line_b_ratio)
        self.calibration_metres = calibration_metres
        self.max_speed_kmh = max_speed_kmh
        self._records: dict[int, _CrossingRecord] = {}
        self._last_seen: dict[int, float] = {}
        log.info(
            "Speed sensor calibrated | line_A_y=%d line_B_y=%d distance=%.1fm max_speed=%.1fkm/h",
            self.line_a_y, self.line_b_y, calibration_metres, max_speed_kmh,
        )

    def update(self, vehicle_id: int, cx: int, cy: int) -> Optional[CrossingEvent]:
        """
        Feed the current centroid of a tracked vehicle.
        Returns a CrossingEvent if a crossing just completed, else None.
        """
        now = time.monotonic()
        self._last_seen[vehicle_id] = now
        self._evict_stale(now)

        rec = self._records.setdefault(vehicle_id, _CrossingRecord(vehicle_id=vehicle_id))
        prev_cy = rec.prev_cy
        rec.prev_cy = cy

        if prev_cy is None:
            # First sighting of this vehicle — no previous position to detect a crossing against.
            return None

        if rec.t_line_a is None and self._crossed(prev_cy, cy, self.line_a_y):
            rec.t_line_a = now
            log.debug("Vehicle %d crossed LINE_A at y=%d t=%.3f", vehicle_id, cy, now)

        if rec.t_line_b is None and self._crossed(prev_cy, cy, self.line_b_y):
            rec.t_line_b = now
            log.debug("Vehicle %d crossed LINE_B at y=%d t=%.3f", vehicle_id, cy, now)

        if rec.t_line_a is None or rec.t_line_b is None:
            return None

        # Both lines crossed — the order determines direction.
        wrong_way = rec.t_line_b < rec.t_line_a
        elapsed = abs(rec.t_line_b - rec.t_line_a)
        # Reset so the same vehicle can be measured again if it comes back
        del self._records[vehicle_id]

        if elapsed <= 0:
            return None
        speed_kmh = (self.calibration_metres / elapsed) * 3.6

        if wrong_way:
            # Wrong-way driving is reported regardless of speed/calibration — direction
            # alone is the safety concern, so the MAX_SPEED_KMH anomaly cap doesn't apply.
            log.warning(
                "Vehicle %d WRONG WAY crossing (elapsed=%.2fs, ~%.1f km/h)",
                vehicle_id, elapsed, speed_kmh,
            )
            return CrossingEvent(speed_kmh=speed_kmh, wrong_way=True)

        if speed_kmh > self.max_speed_kmh:
            log.warning(
                "Calibration anomaly: vehicle=%d speed=%.1f km/h exceeds MAX_SPEED_KMH=%.1f "
                "(elapsed=%.2fs) — check camera stability/line calibration, not alerting",
                vehicle_id, speed_kmh, self.max_speed_kmh, elapsed,
            )
            return None

        log.info("Vehicle %d speed=%.1f km/h (elapsed=%.2fs)", vehicle_id, speed_kmh, elapsed)
        return CrossingEvent(speed_kmh=speed_kmh, wrong_way=False)

    def line_positions(self) -> tuple[int, int]:
        return self.line_a_y, self.line_b_y

    @staticmethod
    def _crossed(prev_y: int, curr_y: int, line_y: int) -> bool:
        """True if the centroid's Y transitioned across line_y, in either direction."""
        return (prev_y < line_y <= curr_y) or (prev_y > line_y >= curr_y)

    def _evict_stale(self, now: float):
        stale = [vid for vid, t in self._last_seen.items() if now - t > self._STALE_TIMEOUT_S]
        for vid in stale:
            self._records.pop(vid, None)
            del self._last_seen[vid]
