#!/usr/bin/env bash
set -euo pipefail

LOCAL_PORT="${LOCAL_PORT:-80}"

if ! command -v ngrok >/dev/null 2>&1; then
  echo "[ERROR] ngrok is not installed."
  echo "[INFO] Install instructions: https://ngrok.com/docs/getting-started/"
  exit 1
fi

if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
  ngrok config add-authtoken "$NGROK_AUTHTOKEN" >/dev/null
fi

echo "[INFO] Starting ngrok tunnel to localhost:$LOCAL_PORT"
echo "[INFO] Set NGROK_AUTHTOKEN env var if auth token is not configured."
echo "[INFO] Press Ctrl+C to stop the tunnel."

ngrok http "$LOCAL_PORT"
