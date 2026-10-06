#!/bin/bash
# Start script for Clinic Management App

echo "Starting Clinic Management System..."

# Ensure Node.js is on PATH (installed at ~/.local/node/bin on this machine)
export PATH="$HOME/.local/node/bin:$PATH"

# Try to install missing system packages via the distro package manager.
install_pkgs() {
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y "$@"
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y "$@"
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm "$@"
  else
    return 1
  fi
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found, attempting to install..."
  install_pkgs python3 python3-venv python3-pip \
    || { echo "ERROR: could not install python3. Install Python 3.8+ manually."; exit 1; }
fi

if ! command -v node >/dev/null 2>&1; then
  echo "node not found, attempting to install..."
  install_pkgs nodejs npm \
    || { echo "ERROR: could not install node. Install Node.js 18+ manually (https://nodejs.org)."; exit 1; }
fi

# Distro repos can ship an old Node.js - refuse to run on anything < 18.
NODE_MAJOR="$(node --version 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/')"
if [ -z "$NODE_MAJOR" ] || [ "$NODE_MAJOR" -lt 18 ]; then
  echo "ERROR: Node.js 18+ is required (found: $(node --version 2>/dev/null))."
  echo "Install a current release from https://nodejs.org (e.g. via NodeSource) and re-run ./start.sh."
  exit 1
fi

# Shared secret between frontend and backend API. Override in production:
#   API_KEY="strong-random-value" ./start.sh
export API_KEY="${API_KEY:-dev-key}"
export FLASK_API_KEY="${FLASK_API_KEY:-$API_KEY}"
if [ "$API_KEY" = "dev-key" ]; then
  echo "WARNING: using default dev API key. Set API_KEY env var in production."
fi

# Persistent session secret (survives restarts so logins aren't wiped)
if [ ! -f ".session_secret" ]; then
  python3 -c "import secrets; print(secrets.token_hex(32))" > .session_secret
  chmod 600 .session_secret
fi
export SESSION_SECRET="$(cat .session_secret)"

# Start Flask backend
cd backend
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt > /dev/null 2>&1
echo "Starting Flask backend on port 5001..."
FLASK_DEBUG=1 PORT=5001 python app.py &
BACKEND_PID=$!
cd ..

# Start Node.js frontend
cd frontend
if [ ! -d "node_modules" ]; then
    echo "Installing Node.js dependencies..."
    npm install > /dev/null 2>&1
fi
echo "Starting Node.js frontend on port 3000..."
npm start &
FRONTEND_PID=$!
cd ..

echo ""
echo "=========================================="
echo "Clinic Management System is running!"
echo "=========================================="
echo "Frontend: http://localhost:3000"
echo "Backend API: http://localhost:5001/api"
echo ""
echo "Press Ctrl+C to stop both servers"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT
wait