import base64
import logging
import os
import time
from datetime import datetime, timezone

import cv2
import numpy as np
import requests
from ultralytics import YOLO

from detector.speed_sensor import SpeedSensor
from detector.anpr import ANPRReader

log = logging.getLogger("pipeline")

# COCO class IDs that we treat as motor vehicles
_VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

# Minimum confidence for YOLOv8 vehicle detections
_DETECT_CONF = 0.40

# Padding (px) added around vehicle bounding box before passing to ANPR
_CROP_PAD = 10

# How long to wait between alert POST retries
_ALERT_RETRY_S = 2
_ALERT_MAX_RETRIES = 3


class DetectionPipeline:
    """
    Per-camera pipeline that stitches together:
      YOLOv8 vehicle detection → ByteTrack → virtual speed sensor → ANPR → alert POST
    """

    def __init__(
        self,
        cam_id: str,
        speed_limit_kmh: float,
        calibration_metres: float,
        line_a_ratio: float,
        line_b_ratio: float,
        alert_api_url: str,
        max_speed_kmh: float = 80.0,
        save_incident_clip: bool = True,
    ):
        self.cam_id = cam_id
        self.speed_limit_kmh = speed_limit_kmh
        self.alert_api_url = alert_api_url
        self.max_speed_kmh = max_speed_kmh
        self.save_incident_clip = save_incident_clip

        log.info("Loading YOLOv8n for vehicle detection...")
        # Downloads yolov8n.pt on first run (~6 MB); replace with a local path if offline.
        self._yolo = YOLO("yolov8n.pt")

        self._anpr = ANPRReader(lp_model_path="yolov8n.pt")  # swap for LP-specific model later
        self._sensor: SpeedSensor | None = None
        self._line_a_ratio = line_a_ratio
        self._line_b_ratio = line_b_ratio
        self._calibration_metres = calibration_metres

        # Frame buffer for clip saving (ring buffer of last N frames)
        self._clip_buffer: list[np.ndarray] = []
        self._clip_buffer_size = 75   # ~3 s at 25 fps

    def process(self, frame: np.ndarray, fps: float):
        h, w = frame.shape[:2]

        if self._sensor is None:
            self._sensor = SpeedSensor(
                h, self._calibration_metres, self._line_a_ratio, self._line_b_ratio,
                max_speed_kmh=self.max_speed_kmh,
            )

        # Maintain rolling frame buffer for clip saving
        self._clip_buffer.append(frame.copy())
        if len(self._clip_buffer) > self._clip_buffer_size:
            self._clip_buffer.pop(0)

        # Run YOLOv8 with ByteTrack
        results = self._yolo.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=list(_VEHICLE_CLASSES.keys()),
            conf=_DETECT_CONF,
            verbose=False,
        )

        for r in results:
            if r.boxes is None or r.boxes.id is None:
                continue
            for box, track_id, cls_id in zip(r.boxes.xyxy, r.boxes.id, r.boxes.cls):
                vid = int(track_id)
                x1, y1, x2, y2 = map(int, box)
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2

                event = self._sensor.update(vid, cx, cy)
                if event is None:
                    continue

                # Wrong-way alerts fire regardless of speed; speeding alerts still
                # need to clear the configured limit.
                if not event.wrong_way and event.speed_kmh <= self.speed_limit_kmh:
                    log.debug("Vehicle %d within limit: %.1f km/h", vid, event.speed_kmh)
                    continue

                speed = event.speed_kmh
                if event.wrong_way:
                    log.warning("WRONG WAY: vehicle=%d cam=%s (~%.1f km/h)", vid, self.cam_id, speed)
                else:
                    log.warning("OVERSPEED: vehicle=%d speed=%.1f km/h cam=%s", vid, speed, self.cam_id)

                # Crop vehicle for ANPR
                px1 = max(0, x1 - _CROP_PAD)
                py1 = max(0, y1 - _CROP_PAD)
                px2 = min(w, x2 + _CROP_PAD)
                py2 = min(h, y2 + _CROP_PAD)
                vehicle_crop = frame[py1:py2, px1:px2]
                plate_text = self._anpr.read(vehicle_crop) if vehicle_crop.size > 0 else ""

                snapshot_b64 = _encode_snapshot(frame)

                clip_path = ""
                if self.save_incident_clip:
                    try:
                        clip_path = self._save_clip(fps)
                    except Exception:
                        log.exception("Clip save failed for vehicle=%d cam=%s — continuing without clip", vid, self.cam_id)
                        clip_path = ""

                try:
                    self._post_alert(speed, plate_text, snapshot_b64, clip_path, wrong_way=event.wrong_way)
                except Exception:
                    log.exception("Alert POST raised unexpectedly for vehicle=%d cam=%s — continuing", vid, self.cam_id)

    def _save_clip(self, fps: float) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        clip_dir = "/data/incidents"
        os.makedirs(clip_dir, exist_ok=True)
        path = os.path.join(clip_dir, f"{self.cam_id}_{ts}.mp4")

        if not self._clip_buffer:
            return ""

        h, w = self._clip_buffer[0].shape[:2]
        out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for f in self._clip_buffer:
            out.write(f)
        out.release()
        log.info("Clip saved: %s", path)
        return path

    def _post_alert(self, speed: float, plate: str, snapshot_b64: str, clip_path: str, wrong_way: bool = False):
        payload = {
            "camera_id": self.cam_id,
            "speed_kmh": round(speed, 1),
            "plate": plate or "UNREAD",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "snapshot_b64": snapshot_b64,
            "clip_path": clip_path,
            "wrong_way": wrong_way,
        }
        for attempt in range(_ALERT_MAX_RETRIES):
            try:
                resp = requests.post(self.alert_api_url, json=payload, timeout=5)
                resp.raise_for_status()
                log.info("Alert posted | plate=%s speed=%.1f", plate, speed)
                return
            except requests.RequestException as exc:
                log.error("Alert POST failed (attempt %d): %s", attempt + 1, exc)
                if attempt < _ALERT_MAX_RETRIES - 1:
                    time.sleep(_ALERT_RETRY_S)


def _encode_snapshot(frame: np.ndarray) -> str:
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return base64.b64encode(buf).decode()
