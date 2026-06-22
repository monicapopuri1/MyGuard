# Garuda — Society Speed-Trap POD

A POD for the AetherEdge Marketplace that does CCTV surveillance for apartment societies in Bangalore — starting with automated overspeeding detection. Garuda is an AetherEdge "Workforce Pod": a Docker Compose blueprint that turns a camera feed (CCTV/RTSP or file) into automated overspeeding detection with WhatsApp alerts to a society's security guard. This document captures the requirements, design, and everything validated/discovered while testing it.

---

## 1. Requirements

### Functional
- Detect motor vehicles (car, motorcycle, bus, truck) in a video stream.
- Track each vehicle across frames.
- Measure real-world speed (km/h) using a virtual two-line speed trap.
- Flag vehicles exceeding a configurable per-camera speed limit.
- Best-effort license-plate read (ANPR) on overspeeding vehicles.
- Send a WhatsApp alert to the guard: speed, plate (if read), snapshot, timestamp, camera ID.
- Store every incident (SQLite) with a snapshot image and a short video clip.
- Suppress duplicate alerts for the same plate within a configurable time window.
- Support multiple cameras per deployment (one detector worker per camera, one shared alert API).
- Recover automatically from camera/DVR disconnects — a reboot shouldn't kill the pod.
- Ship as a Docker Compose blueprint pulling prebuilt images — no source needed on the node.

### Non-functional
- CPU-only inference (no GPU assumed on edge nodes).
- Camera-vendor agnostic — anything that speaks RTSP (or provides a file/USB source).
- WhatsApp via Twilio or Meta Cloud API, with a `mock` provider for testing without real credentials.
- Low-friction local testing without needing a live camera (file-based smoke test).

---

## 2. Assumptions (validated or invalidated during testing)

| Assumption | Status | Notes |
|---|---|---|
| Camera is fixed/stationary | **Required, not optional** | Speed math is `distance ÷ time` between two fixed pixel rows. A handheld/shaky camera produces nonsensical speeds (200+ km/h for a walking person) — confirmed live. |
| Camera can see the vehicle's plate face-on | **Often false for typical CCTV** | Overhead-mounted cameras (common for general society surveillance) see roofs/windshields, never the plate — confirmed by inspecting an actual incident snapshot. Angled cameras (e.g. at a gate) can work. |
| Camera exposes RTSP (pull model) | **True for real CCTV/NVR**, false for phones | NVRs are RTSP *servers* — Garuda just connects directly, no relay needed. Phone broadcaster apps (Larix, etc.) only *push* via RTMP, requiring a relay server (`mediamtx`) to bridge RTMP-in to RTSP-out for testing purposes only. |
| Underlying YOLO model understands "license plate" | **False** | `yolov8n.pt` is generic COCO (80 classes; no plate class). Plate "detection" in `anpr.py` is a non-functional placeholder by the code's own comment — it effectively returns the same vehicle crop it was given, regardless of video quality. |
| `SAVE_INCIDENT_CLIP` env var controls clip-saving | **False — dead config** | The variable exists in `.env.example`/`.env.test` but nothing in `detector/pipeline.py` or `detector/main.py` reads it. Clips are always saved unconditionally. |
| Society NVRs might already do this natively | **Plausible, unconfirmed** | CP Plus NVRs are typically Dahua-OEM; Dahua's IVS "Tripwire" rule supports direction-aware triggers (A→B / B→A / Both) — i.e. wrong-way detection may already be a built-in NVR feature, gated by camera/license tier. Worth checking before building custom. |

---

## 3. High-Level Design (HLD)

### Position in AetherEdge
AetherEdge is a zero-touch edge-node orchestration platform (mTLS node registration, blueprint-based Docker Compose dispatch). Garuda is one "Workforce Pod" blueprint among several (see `orchestrator/blueprints/garuda.yml` in the AetherEdge repo) that an edge node pulls and runs.

### Components

```
┌──────────────────────────┐        ┌──────────────────────────────┐
│   Camera (RTSP / file)   │──────▶ │   detector-cam-NN (1 per cam) │
│  (CCTV/NVR or test file) │        │  YOLOv8n + ByteTrack          │
└──────────────────────────┘        │  → virtual speed sensor       │
                                     │  → ANPR (best-effort)         │
                                     │  → POST /api/v1/alert         │
                                     └───────────────┬────────────────┘
                                                      │ HTTP
                                                      ▼
                                     ┌──────────────────────────────┐
                                     │        alert-api (shared)     │
                                     │  dedup → SQLite store         │
                                     │       → WhatsApp send         │
                                     └──────────────────────────────┘
```

- **One `alert-api`** instance shared across all cameras on a node.
- **One `detector` instance per camera** — add more by duplicating the service block in `garuda.yml`.
- Deployment is via `garuda.yml` (Docker Compose), pulling `monicapopuri/garuda-detector:latest` / `monicapopuri/garuda-alert:latest` from Docker Hub. `build_and_push.sh` publishes new images.

### Data flow
1. Detector reads frames from its camera source.
2. YOLOv8n + ByteTrack detects and tracks vehicles (restricted to car/motorcycle/bus/truck classes).
3. A vehicle's tracked centroid crossing two virtual trip-lines yields elapsed time → speed.
4. If over the limit: crop the vehicle, attempt ANPR, encode a snapshot, save a short clip, POST to `alert-api`.
5. `alert-api` checks dedup (plate + camera, time-windowed), stores the incident in SQLite, saves the snapshot, and sends a WhatsApp message (or logs it, in mock mode).

---

## 4. Low-Level Design (LLD)

### `detector/` (one process per camera)

| File | Responsibility |
|---|---|
| `main.py` | Reads env vars (`CAM_ID`, `CAM_RTSP_URL`, `SPEED_LIMIT_KMH`, `CALIBRATION_METRES`, `LINE_A_Y_RATIO`, `LINE_B_Y_RATIO`, `ALERT_API_URL`), wires `CameraCapture` → `DetectionPipeline`. |
| `capture.py` | `CameraCapture` wraps `cv2.VideoCapture`. Uses `cv2.CAP_FFMPEG` backend specifically for `rtsp://` sources, `CAP_ANY` otherwise (files/USB). `frames()` is a generator with automatic reconnect (5s backoff) on read failure or source-unavailable — proven live by killing/restarting an RTSP feed mid-stream. |
| `pipeline.py` | `DetectionPipeline.process(frame, fps)`: runs `YOLO.track()` with ByteTrack, restricted via `classes=list(_VEHICLE_CLASSES.keys())` to COCO IDs `{2: car, 3: motorcycle, 5: bus, 7: truck}`. Feeds each tracked centroid to `SpeedSensor`. On overspeed: crops the vehicle bbox (+10px pad), runs ANPR, encodes a JPEG snapshot (base64), saves a ~3s rolling clip buffer to `/data/incidents`, and POSTs the alert (3 retries, 2s apart). |
| `speed_sensor.py` | `SpeedSensor`: two horizontal trip-lines at `frame_height * line_a_ratio` / `line_b_ratio`. On a tracked ID's centroid Y crossing line A then line B: `speed_kmh = (calibration_metres / (t_B - t_A)) * 3.6`. Stale (uncompleted) crossings evicted after 10s. **Assumes a stationary camera** — confirmed by testing. |
| `anpr.py` | `ANPRReader`: stage 1 — YOLO locates a plate bbox in the vehicle crop (currently the same generic `yolov8n.pt`, which has no plate class — non-functional placeholder, explicitly flagged in the code's own comment). Stage 2 — EasyOCR reads text from the located crop (or the full vehicle crop as fallback), regex-matched against Indian plate formats. |

### `alert_api/` (one shared FastAPI process)

| File | Responsibility |
|---|---|
| `main.py` | `GET /health`, `POST /api/v1/alert` (dedup check → store → snapshot save → WhatsApp send → 202), `GET /api/v1/incidents`. Incident store and snapshot paths are hardcoded to `/data/incidents/...` (Docker-volume-only path — crashes if run outside the container without that mount). |
| `dedup.py` | `DedupFilter`: thread-safe dict keyed by `(plate.upper(), camera_id)`, suppresses repeats within `DEDUP_WINDOW_SECONDS`. **Fragile when plate text is inconsistent** — confirmed: OCR noise on a non-plate subject produced a different garbled string per frame, defeating the dedup key. |
| `store.py` | `IncidentStore`: SQLAlchemy + SQLite (`incidents` table: id, camera_id, speed_kmh, plate, timestamp, clip_path, created_at). |
| `whatsapp.py` | `WhatsAppSender`: provider selected by `WHATSAPP_PROVIDER` (`twilio` / `meta` / `mock`). Mock just logs the message — used for all testing so far. |

### Deployment files

| File | Purpose |
|---|---|
| `garuda.yml` | Production Compose blueprint — `image:` only (no `build:`), pulls from Docker Hub. |
| `docker-compose.test.yml` | **Local-test-only** override — adds `build:` contexts (so tests run this commit's source, not the published image) and an `env_file: !override` to `.env.test` (since `--env-file` alone does not redirect the hardcoded `env_file: - .env` in `garuda.yml`). |
| `test_with_video.sh` | Phone-video smoke test: generates `.env.test`, brings up both services via Compose with a mock WhatsApp provider. |
| `build_and_push.sh` | One-time multi-arch image build + push to Docker Hub, for production releases. |

---

## 5. End-to-end test flow (what was actually done, chronologically)

1. **Repo recon** — found Garuda's code and an existing-but-broken smoke-test script.
2. **Fixed `test_with_video.sh`** — it passed an invalid `docker compose up -v ...` flag (not a real option) and relied on `--env-file` to redirect a hardcoded `env_file: - .env` (it doesn't). Added `docker-compose.test.yml` to fix both, plus added the missing `lapx` (ByteTrack dependency) to `requirements.detector.txt`, which had been silently auto-installing at container *runtime* instead of build time.
3. **File-based smoke test** — downloaded a real sample traffic clip (Intel's public `sample-videos` repo), ran the full Dockerized pipeline against it. Confirmed end-to-end: detection → speed calc → `OVERSPEED` → clip save → alert POST → dedup → SQLite store → mock WhatsApp message, verified via `/api/v1/incidents`.
4. **ANPR feasibility check** — pulled an actual incident snapshot from that test and visually confirmed the camera's overhead angle makes plate-reading physically impossible, independent of model quality.
5. **Real-world camera recon** — visited the society's NOC. Found CP Plus (~230 cameras, likely Dahua-OEM), one angled/zoomable camera where plates are readable, no boom barrier yet (planned), and that the live-view bitrate observed (~230 Kbps) is almost certainly the low-bandwidth grid substream, not the real recording resolution.
6. **Build-vs-buy check** — researched whether CP Plus/Dahua NVRs already offer direction-aware Tripwire (potential built-in wrong-way detection), to avoid reinventing an existing feature.
7. **Scope decision** — ANPR deprioritized; speed detection + wrong-way detection prioritized (recorded in project memory for continuity).
8. **RTSP path validation (file-based)** — stood up a local `mediamtx` RTSP server, looped the test video into it via `ffmpeg`, and proved `detector/capture.py`'s actual `rtsp://`/FFMPEG code path and its auto-reconnect logic work against a real, live RTSP stream (killed and restarted the feed mid-read).
9. **RTSP path validation (live phone)** — used Larix Broadcaster (RTMP push) into the same relay, confirmed genuinely live frames via snapshot grabs, and clarified the key architectural distinction: real CCTV/NVR cameras are RTSP *servers* (Garuda connects directly, no relay needed in production) — the relay was purely a phone-testing artifact.
10. **At-home live pipeline test** — since the real road is out of phone WiFi range, swapped the detector's watched class from vehicles to `person` (test-only monkeypatch, not a code change) to exercise the full live tracking + speed-trap math indoors. Along the way: installed the ML stack natively on macOS (avoids the Linux-container CUDA-package bloat that caused a Docker build to time out), fixed a missing CA bundle issue (`SSL_CERT_FILE`), and patched around the hardcoded `/data/incidents` path (crashes outside Docker).
11. **Live test results** — a handheld-phone run produced a flood of absurd speeds, diagnosing the camera-must-be-stationary assumption and the OCR-noise-defeats-dedup issue (see §6). A propped-up (stationary) phone, with the subject walking at a normal distance (not brushing the lens), successfully produced a single clean detection → speed → alert cycle, proving the live mechanism end-to-end.

---

## 6. Findings / bugs discovered

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | `test_with_video.sh` used an invalid `docker compose up -v` flag | Blocking | **Fixed** (`docker-compose.test.yml` + script update) |
| 2 | `--env-file` doesn't redirect the hardcoded `env_file: - .env` | Blocking | **Fixed** (`env_file: !override` in test compose file) |
| 3 | `lapx` (ByteTrack dep) missing from `requirements.detector.txt` | Medium — silent runtime auto-install, fails offline | **Fixed** |
| 4 | ANPR's "plate detector" is generic `yolov8n.pt` — no plate class exists in COCO | Known gap (flagged in code) | Open — deprioritized per scope decision |
| 5 | `SAVE_INCIDENT_CLIP` env var is dead config — never read by the code | Low | Open |
| 6 | No error handling around clip-saving (`_save_clip`) — any write failure crashes the *entire* detector process, not just that incident | **Real robustness gap** | Open |
| 7 | Dedup keys strictly on plate text — inconsistent OCR output (common even on real plates under blur/angle) can let duplicate alerts through | Medium | Open |
| 8 | Speed math assumes a stationary camera; no sanity-bound on implausible speeds (e.g. nothing rejects "263 km/h") | Medium | Open |
| 9 | Hardcoded `/data/...` paths in `alert_api/main.py` and `detector/pipeline.py` only work inside the Docker volume mount | Low (by design for prod) | Working as intended in Docker; just noted for local testing |

---

## 7. Open items / next steps

- Get the real RTSP URL + credentials for the society's angled, plate-readable camera (likely Dahua-style: `rtsp://user:pass@ip:554/cam/realmonitor?channel=N&subtype=0`) once ready to test against a live feed.
- Confirm that camera's actual main-stream resolution (NVR encode settings, not the live-grid bitrate).
- Check whether any camera/NVR already has IVS/Smart Plan → Tripwire with direction available and licensed — could simplify or eliminate the need for custom wrong-way detection.
- Design and implement wrong-way detection (currently absent from `speed_sensor.py`).
- Decide on AetherEdge node placement — must be on the same LAN as the NVR (no relay needed for a real camera, unlike the phone-testing setup).
- Fix the robustness gaps in §6 (especially #6 and #7) before any real deployment.
