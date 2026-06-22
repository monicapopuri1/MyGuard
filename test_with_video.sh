#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
#  Garuda — Phone-video smoke test (no live CCTV, no WhatsApp creds)
#
#  Usage:
#    1. Record a 30-60s video of cars on a road using your phone.
#    2. Copy it to this folder as test_video.mp4
#    3. Run:  bash test_with_video.sh
#
#  What it does:
#    • Starts the alert-api with a MOCK whatsapp provider (prints to log, no real send)
#    • Starts the detector pointed at test_video.mp4
#    • You'll see speed readings and (simulated) alerts in the terminal
# ──────────────────────────────────────────────────────────────────
set -e

VIDEO="${1:-test_video.mp4}"

if [ ! -f "$VIDEO" ]; then
  echo "ERROR: Video file '$VIDEO' not found."
  echo "Record a road video on your phone, copy it here as test_video.mp4, then re-run."
  exit 1
fi

echo "Using video: $VIDEO"

# Write a minimal .env for the test (overrides production .env)
cat > .env.test << EOF
SOCIETY_NAME=PFS Society (TEST)
SPEED_LIMIT_KMH=5
WHATSAPP_PROVIDER=mock
GUARD_WHATSAPP_TO=whatsapp:+910000000000
DEDUP_WINDOW_SECONDS=10
SAVE_INCIDENT_CLIP=false
CAM_01_RTSP_URL=/data/test_video.mp4
CAM_01_CALIBRATION_METRES=8.0
CAM_01_LINE_A_Y_RATIO=0.35
CAM_01_LINE_B_Y_RATIO=0.65
EOF

if [ "$(cd "$(dirname "$VIDEO")" && pwd)/$(basename "$VIDEO")" != "$(pwd)/test_video.mp4" ]; then
  echo "Copying video to test_video.mp4 for the container mount..."
  cp "$VIDEO" test_video.mp4
fi

echo "Starting Garuda in test mode (Ctrl+C to stop)..."
docker compose -f garuda.yml -f docker-compose.test.yml \
  --env-file .env.test \
  -p garuda-test \
  up --build
