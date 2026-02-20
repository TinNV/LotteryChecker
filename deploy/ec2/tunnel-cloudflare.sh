#!/usr/bin/env bash
set -euo pipefail

LOCAL_URL="${LOCAL_URL:-http://localhost:80}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "[ERROR] cloudflared is not installed."
  echo "[INFO] Install instructions: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
fi

echo "[INFO] Starting Cloudflare Quick Tunnel to $LOCAL_URL"
echo "[INFO] Press Ctrl+C to stop the tunnel."

cloudflared tunnel --url "$LOCAL_URL"
