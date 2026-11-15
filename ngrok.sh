#!/usr/bin/env bash
set -Eeuo pipefail

PORT="${PORT:-8000}"
APP_URL="http://127.0.0.1:${PORT}"

if ! command -v ngrok >/dev/null 2>&1; then
  echo "ngrok is not installed or is not on PATH." >&2
  echo "Install it from https://ngrok.com/download, then run: ngrok config add-authtoken <TOKEN>" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to verify that Screen2Care is running." >&2
  exit 1
fi

if ! curl --fail --silent --show-error --max-time 5 "${APP_URL}/health" >/dev/null; then
  echo "Screen2Care is not healthy at ${APP_URL}." >&2
  echo "Start it first with: bash main.sh" >&2
  exit 1
fi

echo "Tunneling Screen2Care at ${APP_URL}"
echo "Keep this terminal open while sharing the ngrok URL."
exec ngrok http "${PORT}"
