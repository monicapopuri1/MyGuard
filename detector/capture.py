import time
import logging
import cv2

log = logging.getLogger("capture")

_RECONNECT_DELAY_S = 5
_RTSP_OPTIONS = {
    cv2.CAP_PROP_BUFFERSIZE: 1,
}


class CameraCapture:
    """
    Wraps cv2.VideoCapture to handle RTSP streams, local files, and USB cameras.
    Reconnects automatically on disconnect so a DVR reboot doesn't kill the POD.
    """

    def __init__(self, source: str):
        self.source = source
        self._cap = None

    def _open(self) -> cv2.VideoCapture:
        log.info("Opening video source: %s", self.source)
        # Use FFMPEG backend for RTSP; default backend for files/USB
        backend = cv2.CAP_FFMPEG if self.source.startswith("rtsp://") else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.source, backend)
        for prop, val in _RTSP_OPTIONS.items():
            cap.set(prop, val)
        if not cap.isOpened():
            raise IOError(f"Cannot open video source: {self.source}")
        return cap

    def frames(self):
        """
        Generator that yields (frame, fps) tuples indefinitely.
        Re-opens the source on failure with exponential-ish back-off.
        """
        while True:
            try:
                self._cap = self._open()
                fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
                log.info("Stream opened | fps=%.1f", fps)

                while True:
                    ret, frame = self._cap.read()
                    if not ret:
                        log.warning("Frame read failed — reconnecting in %ds", _RECONNECT_DELAY_S)
                        break
                    yield frame, fps

            except IOError as exc:
                log.error("Source unavailable: %s — retrying in %ds", exc, _RECONNECT_DELAY_S)
            finally:
                if self._cap:
                    self._cap.release()
                    self._cap = None

            time.sleep(_RECONNECT_DELAY_S)
