#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:0.5b}"

cd "$ROOT"

if [ ! -d ".venv" ]; then
  "$PYTHON" -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --upgrade setuptools wheel
python -m pip install -r backend/requirements.txt
python scripts/download_models.py

if command -v ollama >/dev/null 2>&1; then
  . scripts/pi_fast_env.sh
  ollama pull "$OLLAMA_MODEL"
else
  echo "Ollama was not found. Install it, then run: ollama pull $OLLAMA_MODEL"
fi

chmod +x scripts/run_pi_fast.sh scripts/pi_fast_env.sh

echo "Install whisper.cpp and Piper binaries, then set ECHO_WHISPER_CPP_BIN and ECHO_PIPER_BIN if needed."
echo "Run fast profile: scripts/run_pi_fast.sh"
