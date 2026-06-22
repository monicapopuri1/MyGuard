import base64
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from alert_api.dedup import DedupFilter
from alert_api.store import IncidentStore
from alert_api.whatsapp import WhatsAppSender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GARUDA-%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("alert-api")

app = FastAPI(title="Garuda Alert API", version="1.0.0")

_dedup = DedupFilter(window_seconds=int(os.environ.get("DEDUP_WINDOW_SECONDS", "60")))
_store = IncidentStore(db_path="/data/incidents/garuda.db")
_sender = WhatsAppSender()
_society = os.environ.get("SOCIETY_NAME", "Society")
_speed_limit = float(os.environ.get("SPEED_LIMIT_KMH", "20"))


class AlertPayload(BaseModel):
    camera_id: str
    speed_kmh: float
    plate: str
    timestamp: str
    snapshot_b64: str = ""
    clip_path: str = ""


@app.get("/health")
def health():
    return {"status": "ok", "service": "garuda-alert-api"}


@app.post("/api/v1/alert", status_code=202)
def receive_alert(payload: AlertPayload):
    log.info("Alert received | cam=%s plate=%s speed=%.1f", payload.camera_id, payload.plate, payload.speed_kmh)

    if _dedup.is_duplicate(payload.plate, payload.camera_id):
        log.info("Suppressed duplicate alert for plate=%s", payload.plate)
        return {"status": "suppressed", "reason": "dedup_window"}

    incident_id = _store.save(
        camera_id=payload.camera_id,
        speed_kmh=payload.speed_kmh,
        plate=payload.plate,
        timestamp=payload.timestamp,
        clip_path=payload.clip_path,
    )

    if payload.snapshot_b64:
        _save_snapshot(payload.snapshot_b64, incident_id)

    message = _build_message(payload)
    try:
        _sender.send(message)
    except Exception as exc:
        log.error("WhatsApp send failed: %s", exc)
        # Don't raise — incident is already stored; alert can be resent manually.

    _dedup.record(payload.plate, payload.camera_id)
    return {"status": "accepted", "incident_id": incident_id}


@app.get("/api/v1/incidents")
def list_incidents(limit: int = 50):
    return _store.recent(limit)


def _build_message(p: AlertPayload) -> str:
    try:
        dt = datetime.fromisoformat(p.timestamp).astimezone()
        formatted_time = dt.strftime("%d %b %Y, %H:%M:%S")
    except Exception:
        formatted_time = p.timestamp

    return (
        f"🚨 *SPEEDING ALERT — {_society}*\n"
        f"Camera  : {p.camera_id}\n"
        f"Speed   : *{p.speed_kmh} km/h*  (limit: {int(_speed_limit)} km/h)\n"
        f"Plate   : *{p.plate}*\n"
        f"Time    : {formatted_time}\n"
        f"_Powered by Garuda / AetherEdge_"
    )


def _save_snapshot(b64_data: str, incident_id: str):
    try:
        img_bytes = base64.b64decode(b64_data)
        path = f"/data/incidents/{incident_id}.jpg"
        with open(path, "wb") as f:
            f.write(img_bytes)
        log.info("Snapshot saved: %s", path)
    except Exception as exc:
        log.warning("Could not save snapshot: %s", exc)
