#!/usr/bin/env bash
# AI ComicVerse - one-shot local launcher (Linux / macOS / Git Bash).
#
#   bash scripts/run_local.sh
#
# Creates a venv, installs the backend, runs uvicorn, then installs and runs the
# frontend. Ctrl-C stops both. Add GEMINI_API_KEY to backend/.env for Gemini;
# Pollinations is used for panel images by default.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend="$root/backend"
frontend="$root/frontend"
venv="$backend/.venv"
python="$venv/bin/python"

echo "=== AI ComicVerse : local run ==="

if [ ! -x "$python" ]; then
  echo "-> creating the backend virtualenv"
  python3 -m venv "$venv"
fi

echo "-> installing backend dependencies"
"$python" -m pip install --upgrade pip --quiet
"$python" -m pip install -r "$backend/requirements.txt" --quiet

if [ ! -f "$backend/.env" ]; then
  cp "$backend/.env.example" "$backend/.env"
  echo "-> created backend/.env from .env.example; add GEMINI_API_KEY for Gemini text analysis"
fi

if [ ! -d "$frontend/node_modules" ]; then
  echo "-> installing frontend dependencies"
  (cd "$frontend" && npm install --no-audit --no-fund)
fi

cleanup() {
  echo ""
  echo "-> shutting down"
  [ -n "${api_pid:-}" ] && kill "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "-> API on http://127.0.0.1:8000 (docs at /docs)"
(cd "$backend" && "$python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &
api_pid=$!

sleep 3

echo "-> UI on http://localhost:5173"
cd "$frontend"
npm run dev
