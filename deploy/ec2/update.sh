#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/ec2/docker-compose.yml"
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

if ! command -v git >/dev/null 2>&1; then
  echo "[ERROR] Git is not installed."
  exit 1
fi

cd "$ROOT_DIR"
load_env_file

echo "[INFO] Pulling latest code..."
git pull --ff-only

echo "[INFO] Rebuilding and restarting LotteryChecker..."
run_compose "$COMPOSE_FILE" up -d --build --remove-orphans

echo "[INFO] Cleaning dangling Docker images..."
docker image prune -f >/dev/null || true

echo "[INFO] Service status:"
run_compose "$COMPOSE_FILE" ps

echo "[INFO] Update complete."
