import logging
import re
import cv2
import numpy as np
import easyocr
from ultralytics import YOLO

log = logging.getLogger("anpr")

# Regex for Indian license plates: 2 letters + 2 digits + optional space + 1-2 letters + 4 digits
# Covers both old-format (MH12AB1234) and BH-series (23BH1234AA)
_PLATE_PATTERN = re.compile(
    r"([A-Z]{2}\s?\d{2}\s?[A-Z]{1,2}\s?\d{4}|"   # State format
    r"\d{2}BH\s?\d{4}\s?[A-Z]{1,2})",              # BH series
    re.IGNORECASE,
)

_MIN_PLATE_AREA = 400   # px² — ignore tiny detections


class ANPRReader:
    """
    Two-stage ANPR:
    1. YOLOv8n (fine-tuned for license plates) locates the plate bounding box in the vehicle crop.
    2. EasyOCR reads the alphanumeric text from the plate crop.

    Falls back to reading OCR directly on the vehicle ROI if YOLO finds no plate.
    """

    def __init__(self, lp_model_path: str = "yolov8n.pt"):
        log.info("Loading license-plate detector: %s", lp_model_path)
        # Use a generic YOLOv8n when a fine-tuned LP model is not yet available;
        # replace with a proper LP-detection weight for production.
        self._yolo = YOLO(lp_model_path)
        log.info("Loading EasyOCR (en)...")
        self._ocr = easyocr.Reader(["en"], gpu=False, verbose=False)
        log.info("ANPR ready")

    def read(self, vehicle_crop: np.ndarray) -> str:
        """
        Returns the best plate string found in the vehicle crop, or empty string.
        """
        plate_img = self._locate_plate(vehicle_crop)
        if plate_img is None:
            plate_img = vehicle_crop   # fall back to full vehicle crop

        text = self._ocr_plate(plate_img)
        return text

    def _locate_plate(self, img: np.ndarray) -> np.ndarray | None:
        results = self._yolo(img, verbose=False, conf=0.25)
        best_box = None
        best_area = _MIN_PLATE_AREA

        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                area = (x2 - x1) * (y2 - y1)
                if area > best_area:
                    best_area = area
                    best_box = (x1, y1, x2, y2)

        if best_box is None:
            return None

        x1, y1, x2, y2 = best_box
        crop = img[max(0, y1):y2, max(0, x1):x2]
        return crop if crop.size > 0 else None

    def _ocr_plate(self, plate_img: np.ndarray) -> str:
        # Upscale small plates to improve OCR accuracy
        h, w = plate_img.shape[:2]
        if h < 40:
            scale = 40 / h
            plate_img = cv2.resize(plate_img, (int(w * scale), 40), interpolation=cv2.INTER_CUBIC)

        results = self._ocr.readtext(plate_img, detail=0, paragraph=False)
        raw = " ".join(results).upper().strip()
        raw_clean = re.sub(r"[^A-Z0-9]", "", raw)

        match = _PLATE_PATTERN.search(raw_clean)
        if match:
            return match.group(0).upper().replace(" ", "")

        # Return raw cleaned text if pattern doesn't match (e.g., old/worn plates)
        return raw_clean if len(raw_clean) >= 4 else ""
