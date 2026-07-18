#!/usr/bin/env bash
# Start the FastAPI OTP auth microservice.
# Usage:  bash run.sh        (or)  chmod +x run.sh && ./run.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Create a virtual env (skip if it already exists).
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

# 2. Activate it + install deps.
# shellcheck disable=SC1091
source .venv/bin/activate
echo "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 3. Make sure the data dir exists for SQLite.
mkdir -p data

# 4. Launch uvicorn with auto-reload.
PORT="${PORT:-8000}"
echo "------------------------------------------------------------"
echo "  FastAPI OTP Auth Microservice"
echo "  Listening:  http://localhost:${PORT}"
echo "  Swagger UI: http://localhost:${PORT}/docs"
echo "  ReDoc:      http://localhost:${PORT}/redoc"
echo "  Press Ctrl+C to stop."
echo "------------------------------------------------------------"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
