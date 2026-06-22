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
- All 4 priority fixes done, tested, committed, and pushed (ef0776f)

## Completed Today
- Fix 1: _save_clip() / alert-POST crash — wrapped in try/except, logs full traceback, never kills the detector
- Fix 2: Dedup OCR noise — falls back to (camera_id, time_bucket) key when plate is empty/garbled
- Fix 3: Speed sanity check — added configurable MAX_SPEED_KMH (default 80), anomalies logged not alerted
- Fix 4: Wired up SAVE_INCIDENT_CLIP env var (was dead config, now actually gates clip saving)
- All 4 verified with targeted tests, committed and pushed to main

## In Progress
- Nothing right now — waiting to start Feature 1 (wrong way detection)

## Pending Fixes (in order)
- None — all 4 done

## Pending Features (after fixes)
- Wrong way detection (NEXT UP)
- Daily status report
- Real NVR RTSP testing

## Known Working
- detector/capture.py RTSP reconnect ✓
- detector/pipeline.py detection ✓
- alert_api WhatsApp mock ✓
- SQLite incident storage ✓
- Docker Compose deployment ✓
- detector/pipeline.py clip-save/alert-POST failures no longer crash the process ✓
- alert_api/dedup.py suppresses repeats even with garbled/empty plate reads ✓
- detector/speed_sensor.py caps absurd speeds via MAX_SPEED_KMH ✓
- SAVE_INCIDENT_CLIP env var now actually controls clip saving ✓

## Known Issues
- None open from the original 4 — next known gap is the missing wrong-way detection logic in speed_sensor.py

## Environment
- CP Plus NVR — Dahua OEM
- RTSP format: rtsp://user:pass@ip:554/
  cam/realmonitor?channel=N&subtype=0
- Society: ~230 cameras
- Target: Bengaluru housing society
