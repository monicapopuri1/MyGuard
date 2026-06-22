import time
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("speed_sensor")


@dataclass
class _CrossingRecord:
    vehicle_id: int
    t_line_a: Optional[float] = None
    t_line_b: Optional[float] = None
    centroid_at_a: Optional[tuple] = None


class SpeedSensor:
    """
    Virtual two-line speed trap.

    A vehicle is timed between LINE_A and LINE_B.
    Speed = calibration_metres / elapsed_seconds * 3.6  (km/h)

    LINE_A and LINE_B are horizontal pixel rows at fixed Y ratios of the frame height.
    A vehicle "crosses" a line when its centroid Y transitions from one side to the other.
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

    def update(self, vehicle_id: int, cx: int, cy: int) -> Optional[float]:
        """
        Feed the current centroid of a tracked vehicle.
        Returns computed speed in km/h if a crossing is complete, else None.
        """
        now = time.monotonic()
        self._last_seen[vehicle_id] = now
        self._evict_stale(now)

        rec = self._records.setdefault(vehicle_id, _CrossingRecord(vehicle_id=vehicle_id))

        # Line A crossing (vehicle moves downward past line A)
        if rec.t_line_a is None and cy >= self.line_a_y:
            rec.t_line_a = now
            rec.centroid_at_a = (cx, cy)
            log.debug("Vehicle %d crossed LINE_A at y=%d t=%.3f", vehicle_id, cy, now)
            return None

        # Line B crossing (vehicle continues past line B)
        if rec.t_line_a is not None and rec.t_line_b is None and cy >= self.line_b_y:
            rec.t_line_b = now
            elapsed = rec.t_line_b - rec.t_line_a
            if elapsed <= 0:
                return None
            speed_kmh = (self.calibration_metres / elapsed) * 3.6
            # Reset so the same vehicle can be measured again if it comes back
            del self._records[vehicle_id]

            if speed_kmh > self.max_speed_kmh:
                log.warning(
                    "Calibration anomaly: vehicle=%d speed=%.1f km/h exceeds MAX_SPEED_KMH=%.1f "
                    "(elapsed=%.2fs) — check camera stability/line calibration, not alerting",
                    vehicle_id, speed_kmh, self.max_speed_kmh, elapsed,
                )
                return None

            log.info("Vehicle %d speed=%.1f km/h (elapsed=%.2fs)", vehicle_id, speed_kmh, elapsed)
            return speed_kmh

        return None

    def line_positions(self) -> tuple[int, int]:
        return self.line_a_y, self.line_b_y

    def _evict_stale(self, now: float):
        stale = [vid for vid, t in self._last_seen.items() if now - t > self._STALE_TIMEOUT_S]
        for vid in stale:
            self._records.pop(vid, None)
            del self._last_seen[vid]
