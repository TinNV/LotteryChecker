#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_ENV_FILE="${ROOT_DIR}/.env"
REMOTE_USER="ec2-user"
REMOTE_DIR="~/lottery-checker"
PORT="22"
HOST_NAME=""
KEY_FILE=""

usage() {
  cat <<'EOF'
Usage:
  ./deploy/ec2/copy-env-to-ec2.sh --host <hostname-or-ip> --key <pem-file> [options]

Options:
  --user <remote-user>         Default: ec2-user
  --remote-dir <remote-path>   Default: ~/lottery-checker
  --env-file <local-env-file>  Default: <repo>/.env
  --port <ssh-port>            Default: 22
  -h, --help                   Show help
EOF
}

require_arg_value() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "$value" || "$value" == --* ]]; then
    echo "[ERROR] Missing value for ${flag}"
    usage
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      require_arg_value "$1" "${2:-}"
      HOST_NAME="$2"
      shift 2
      ;;
    --key)
      require_arg_value "$1" "${2:-}"
      KEY_FILE="$2"
      shift 2
      ;;
    --user)
      require_arg_value "$1" "${2:-}"
      REMOTE_USER="$2"
      shift 2
      ;;
    --remote-dir)
      require_arg_value "$1" "${2:-}"
      REMOTE_DIR="$2"
      shift 2
      ;;
    --env-file)
      require_arg_value "$1" "${2:-}"
      LOCAL_ENV_FILE="$2"
      shift 2
      ;;
    --port)
      require_arg_value "$1" "${2:-}"
      PORT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$HOST_NAME" ]]; then
  echo "[ERROR] Missing required argument: --host"
  usage
  exit 1
fi

if [[ -z "$KEY_FILE" ]]; then
  echo "[ERROR] Missing required argument: --key"
  usage
  exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "[ERROR] ssh is not installed."
  exit 1
fi

if ! command -v scp >/dev/null 2>&1; then
  echo "[ERROR] scp is not installed."
  exit 1
fi

if [[ ! -f "$LOCAL_ENV_FILE" ]]; then
  echo "[ERROR] .env file not found: $LOCAL_ENV_FILE"
  exit 1
fi

if [[ ! -f "$KEY_FILE" ]]; then
  echo "[ERROR] SSH key file not found: $KEY_FILE"
  exit 1
fi

REMOTE_ENV_PATH="${REMOTE_DIR}/.env"

echo "[INFO] Ensuring remote directory exists: ${REMOTE_DIR}"
ssh -i "$KEY_FILE" -p "$PORT" -o StrictHostKeyChecking=accept-new \
  "${REMOTE_USER}@${HOST_NAME}" "mkdir -p ${REMOTE_DIR}"

echo "[INFO] Copying ${LOCAL_ENV_FILE} to ${REMOTE_USER}@${HOST_NAME}:${REMOTE_ENV_PATH}"
scp -i "$KEY_FILE" -P "$PORT" -o StrictHostKeyChecking=accept-new \
  "$LOCAL_ENV_FILE" "${REMOTE_USER}@${HOST_NAME}:${REMOTE_ENV_PATH}"

echo "[INFO] Setting secure permission on remote .env"
ssh -i "$KEY_FILE" -p "$PORT" -o StrictHostKeyChecking=accept-new \
  "${REMOTE_USER}@${HOST_NAME}" "chmod 600 ${REMOTE_ENV_PATH} && ls -l ${REMOTE_ENV_PATH}"

echo "[INFO] Done."
