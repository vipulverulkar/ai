#!/bin/bash
# Production startup for Clinic Management System.
# Required env vars: API_KEY, SESSION_SECRET
# Optional: PORT (backend, default 5001), FRONTEND_PORT (default 3000),
#   ADMIN_USERNAME, ADMIN_PASSWORD, CORS_ORIGINS, FLASK_API (frontend -> backend URL)

set -e
export PATH="$HOME/.local/node/bin:$PATH"
: "${API_KEY:?Set API_KEY env var to a strong random value}"
: "${SESSION_SECRET:?Set SESSION_SECRET env var to a strong random value}"
export FLASK_API_KEY="${FLASK_API_KEY:-$API_KEY}"

echo "Starting Clinic Management System (production)..."

cd backend
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt > /dev/null 2>&1
echo "Starting gunicorn backend on port ${PORT:-5001}..."
PORT="${PORT:-5001}" ./venv/bin/gunicorn "app:app" --workers 2 --bind "0.0.0.0:${PORT:-5001}" &
BACKEND_PID=$!
cd ..

cd frontend
if [ ! -d "node_modules" ]; then
    npm install --omit=dev > /dev/null 2>&1
fi
echo "Starting Node.js frontend on port ${FRONTEND_PORT:-3000}..."
NODE_ENV=production PORT="${FRONTEND_PORT:-3000}" FLASK_API="${FLASK_API:-http://localhost:5001/api}" npm start &
FRONTEND_PID=$!
cd ..

echo "Production servers running. Press Ctrl+C to stop."
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
