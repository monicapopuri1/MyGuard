import os
import logging
import sys
import signal
from detector.capture import CameraCapture
from detector.pipeline import DetectionPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GARUDA-%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("main")


class GracefulShutdown:
    """
    Handles SIGTERM (Kubernetes) and SIGINT (Ctrl+C) gracefully.

    When a shutdown signal is received, sets a flag that the main loop checks.
    This allows the detector to finish processing the current frame and
    cleanly release resources instead of being forcefully killed mid-operation.
    """

    def __init__(self):
        self.should_stop = False
        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigterm(self, signum, frame):
        """Called when Kubernetes sends SIGTERM (pod shutdown)."""
        log.info("SIGTERM received — initiating graceful shutdown")
        self.should_stop = True

    def _handle_sigint(self, signum, frame):
        """Called when user presses Ctrl+C."""
        log.info("SIGINT received — initiating graceful shutdown")
        self.should_stop = True


def main():
    cam_id = os.environ["CAM_ID"]
    source = os.environ["CAM_RTSP_URL"]
    speed_limit = float(os.environ.get("SPEED_LIMIT_KMH", "20"))
    calibration_metres = float(os.environ.get("CALIBRATION_METRES", "8.0"))
    line_a_ratio = float(os.environ.get("LINE_A_Y_RATIO", "0.35"))
    line_b_ratio = float(os.environ.get("LINE_B_Y_RATIO", "0.65"))
    max_speed_kmh = float(os.environ.get("MAX_SPEED_KMH", "80"))
    save_incident_clip = os.environ.get(
        "SAVE_INCIDENT_CLIP", "true").strip().lower() in ("1", "true", "yes", "on")
    alert_url = os.environ.get(
        "ALERT_API_URL", "http://alert-api:8090/api/v1/alert")

    log.info("Garuda detector starting | cam=%s source=%s limit=%s km/h",
             cam_id, source, speed_limit)

    # Set up graceful shutdown handler
    shutdown = GracefulShutdown()

    capture = CameraCapture(source)
    pipeline = DetectionPipeline(
        cam_id=cam_id,
        speed_limit_kmh=speed_limit,
        calibration_metres=calibration_metres,
        line_a_ratio=line_a_ratio,
        line_b_ratio=line_b_ratio,
        alert_api_url=alert_url,
        max_speed_kmh=max_speed_kmh,
        save_incident_clip=save_incident_clip,
    )

    # Main processing loop with shutdown check and exception handling
    try:
        for frame, fps in capture.frames():
            # Check if shutdown signal was received
            if shutdown.should_stop:
                log.info("Shutdown signal detected; stopping detector gracefully")
                break

            try:
                pipeline.process(frame, fps)
            except Exception:
                log.exception(
                    "Frame processing failed; skipping frame and continuing")
                continue
    finally:
        # Cleanup
        if hasattr(capture, '_cap') and capture._cap:
            capture._cap.release()
        log.info("Garuda detector stopped gracefully")


if __name__ == "__main__":
    main()
