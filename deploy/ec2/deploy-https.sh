#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/ec2/docker-compose.https.yml"
LEGACY_COMPOSE_FILE="$ROOT_DIR/deploy/ec2/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"

load_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
    echo "[INFO] Loaded env from $ENV_FILE"
  fi
}

run_compose() {
  local compose_file="$1"
  shift
  local cmd=(docker compose)
  if [[ -f "$ENV_FILE" ]]; then
    cmd+=(--env-file "$ENV_FILE")
  fi
  cmd+=(-f "$compose_file")
  "${cmd[@]}" "$@"
}

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] Docker is not installed."
  exit 1
fi

cd "$ROOT_DIR"
load_env_file

if [[ -z "${DOMAIN:-}" ]]; then
  echo "[ERROR] DOMAIN is required. Example: DOMAIN=lottery.example.com ./deploy/ec2/deploy-https.sh"
  exit 1
fi

echo "[INFO] Stopping legacy HTTP stack if running..."
run_compose "$LEGACY_COMPOSE_FILE" down --remove-orphans >/dev/null 2>&1 || true

echo "[INFO] Building and starting LotteryChecker with HTTPS..."
run_compose "$COMPOSE_FILE" up -d --build --remove-orphans

echo "[INFO] Service status:"
run_compose "$COMPOSE_FILE" ps

echo "[INFO] Deployment complete."
echo "[INFO] URL: https://$DOMAIN/"
