#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/ec2/docker-compose.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] Docker is not installed."
  exit 1
fi

cd "$ROOT_DIR"

echo "[INFO] Building and starting LotteryChecker..."
docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

echo "[INFO] Service status:"
docker compose -f "$COMPOSE_FILE" ps

echo "[INFO] Deployment complete."
