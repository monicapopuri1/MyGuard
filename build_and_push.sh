#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
#  Garuda — Build & Push Docker images to Docker Hub
#
#  Run this once from the myGaurd/ directory before deploying
#  the POD to the cloud AetherEdge orchestrator.
#
#  Pre-requisites:
#    • Docker Desktop running
#    • Logged in to Docker Hub:  docker login
#    • (Optional) Docker Buildx for multi-platform builds
#
#  Usage:
#    bash build_and_push.sh             # builds + pushes latest
#    bash build_and_push.sh 1.0.1       # builds + pushes a versioned tag too
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

REGISTRY="monicapopuri"
DETECTOR_IMAGE="${REGISTRY}/garuda-detector"
ALERT_IMAGE="${REGISTRY}/garuda-alert"
TAG="${1:-latest}"

echo "========================================="
echo " Garuda — Build & Push"
echo " Registry : ${REGISTRY}"
echo " Tag      : ${TAG}"
echo "========================================="

# ── Confirm Docker is running ──────────────────────────────────────
if ! docker info > /dev/null 2>&1; then
  echo "ERROR: Docker is not running. Start Docker Desktop and try again."
  exit 1
fi

# ── Confirm logged in ─────────────────────────────────────────────
if ! docker system info --format '{{.RegistryConfig.IndexConfigs}}' 2>/dev/null | grep -q "docker.io"; then
  echo "You don't appear to be logged in to Docker Hub."
  echo "Run:  docker login"
  exit 1
fi

# ── Build detector image ───────────────────────────────────────────
echo ""
echo "▶ Building detector image..."
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f Dockerfile.detector \
  -t "${DETECTOR_IMAGE}:latest" \
  ${TAG:+"-t" "${DETECTOR_IMAGE}:${TAG}"} \
  --push \
  .

echo "✓ Detector image pushed: ${DETECTOR_IMAGE}:latest"

# ── Build alert image ──────────────────────────────────────────────
echo ""
echo "▶ Building alert image..."
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f Dockerfile.alert \
  -t "${ALERT_IMAGE}:latest" \
  ${TAG:+"-t" "${ALERT_IMAGE}:${TAG}"} \
  --push \
  .

echo "✓ Alert image pushed: ${ALERT_IMAGE}:latest"

# ── Done ───────────────────────────────────────────────────────────
echo ""
echo "========================================="
echo " Done! Images are live on Docker Hub."
echo ""
echo " Next steps:"
echo " 1. Copy garuda.yml to the cloud orchestrator's blueprints/ folder"
echo " 2. Copy deploy.py  to the cloud orchestrator's routers/ folder"
echo " 3. Restart the orchestrator"
echo " 4. Deploy Garuda from the AetherEdge marketplace to your node"
echo "========================================="
