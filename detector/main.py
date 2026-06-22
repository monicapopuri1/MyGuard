import os
import logging
import sys
from detector.capture import CameraCapture
from detector.pipeline import DetectionPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GARUDA-%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("main")


def main():
    cam_id = os.environ["CAM_ID"]
    source = os.environ["CAM_RTSP_URL"]
    speed_limit = float(os.environ.get("SPEED_LIMIT_KMH", "20"))
    calibration_metres = float(os.environ.get("CALIBRATION_METRES", "8.0"))
    line_a_ratio = float(os.environ.get("LINE_A_Y_RATIO", "0.35"))
    line_b_ratio = float(os.environ.get("LINE_B_Y_RATIO", "0.65"))
    alert_url = os.environ.get("ALERT_API_URL", "http://alert-api:8090/api/v1/alert")

    log.info("Garuda detector starting | cam=%s source=%s limit=%s km/h", cam_id, source, speed_limit)

    capture = CameraCapture(source)
    pipeline = DetectionPipeline(
        cam_id=cam_id,
        speed_limit_kmh=speed_limit,
        calibration_metres=calibration_metres,
        line_a_ratio=line_a_ratio,
        line_b_ratio=line_b_ratio,
        alert_api_url=alert_url,
    )

    for frame, fps in capture.frames():
        pipeline.process(frame, fps)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Garuda detector stopped.")
        sys.exit(0)
