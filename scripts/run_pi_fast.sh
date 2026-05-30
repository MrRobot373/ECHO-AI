#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

cd "$ROOT"

if [ ! -d ".venv" ]; then
  echo ".venv not found. Run scripts/setup_pi.sh first." >&2
  exit 1
fi

. scripts/pi_fast_env.sh

exec .venv/bin/python -m uvicorn backend.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --workers 1 \
  --no-access-log
