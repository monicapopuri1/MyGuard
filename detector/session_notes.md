# MyGuard Session Notes

## Last Updated: 22 June 2026

## Current Status
- End to end pipeline working on test video
- Live RTSP stream tested via Larix + mediamtx
- WhatsApp mock alerts working
- SQLite storage working
- Docker images published to Hub
- Auto reconnect on RTSP drop proven
- Society visited — CP Plus ~230 cameras
- Vendor contact pending for RTSP credentials

## Completed Today
- Nothing yet this session

## In Progress
- Fix 1: Clip save crash (STARTING NOW)

## Pending Fixes (in order)
- Fix 1: _save_clip() crash — CRITICAL
- Fix 2: Dedup OCR noise — HIGH
- Fix 3: Speed sanity check — MEDIUM
- Fix 4: Dead SAVE_INCIDENT_CLIP — LOW

## Pending Features (after fixes)
- Wrong way detection
- Daily status report
- Real NVR RTSP testing

## Known Working
- detector/capture.py RTSP reconnect ✓
- detector/pipeline.py detection ✓
- alert_api WhatsApp mock ✓
- SQLite incident storage ✓
- Docker Compose deployment ✓

## Known Issues
- _save_clip() crash kills detector
- Dedup fails on OCR noise
- No speed sanity cap
- SAVE_INCIDENT_CLIP dead config

## Environment
- CP Plus NVR — Dahua OEM
- RTSP format: rtsp://user:pass@ip:554/
  cam/realmonitor?channel=N&subtype=0
- Society: ~230 cameras
- Target: Bengaluru housing society