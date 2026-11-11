#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

echo "[1/7] Preparing environment file..."
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "[2/7] Starting PostgreSQL..."
docker compose up -d db

echo "[3/7] Waiting for PostgreSQL..."
for attempt in {1..60}; do
  if docker exec screening_db pg_isready -U loop -d screening_care_loop >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo "PostgreSQL did not become ready in time." >&2
    exit 1
  fi
  sleep 2
done

echo "[4/7] Applying safe database migrations..."
for migration in db/12_loop_closure.sql db/13_followup_loop.sql db/14_biopsy_booking.sql db/15_oncology_referral.sql; do
  echo "Applying $migration"
  docker exec -i screening_db psql -v ON_ERROR_STOP=1 \
    -U loop -d screening_care_loop < "$migration"
done

PYTHON_BIN=python
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python3
fi

echo "[5/7] Creating and activating virtual environment..."
if [[ -x .venv/bin/python ]]; then
  source .venv/bin/activate
elif [[ -x .venv/Scripts/python.exe ]]; then
  source .venv/Scripts/activate
else
  "$PYTHON_BIN" -m venv .venv
  if [[ -x .venv/bin/python ]]; then
    source .venv/bin/activate
  else
    source .venv/Scripts/activate
  fi
fi

echo "[6/7] Installing Python dependencies..."
python -m pip install --upgrade pip
python -m pip install ".[dev]"

echo "[7/7] Seeding users and initializing the rules engine..."
python -m app.seed_users
python -m app.care_loop

echo "Starting Screen2Care at http://localhost:8000"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
