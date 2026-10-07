#!/usr/bin/env bash
# ============================================================
#  Daily Expense Tracker — Launcher (Linux / macOS)
#  - Auto-detects python3 / python
#  - Auto-installs requirements.txt if present
#  - Launches the app (expense_tracker.py)
# ============================================================
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "============================================================"
echo "  Daily Expense Tracker — Launcher (Linux/macOS)"
echo "============================================================"
echo ""

# -- find Python --
PY=""
if command -v python3 >/dev/null 2>&1; then PY="python3"
elif command -v python >/dev/null 2>&1; then PY="python"
else
  echo "[ERROR] Python not found. Install Python 3.10+ from https://www.python.org/"
  exit 1
fi
echo "[1/3] Python: $($PY --version)"
echo ""

# -- check tkinter --
if ! $PY -c "import tkinter" 2>/dev/null; then
  echo "[WARN] tkinter not available."
  echo "       Debian/Ubuntu: sudo apt install python3-tk"
  echo "       Fedora:        sudo dnf install python3-tkinter"
  echo "       macOS:         brew install python-tk  (or reinstall python.org pkg)"
  echo ""
fi

# -- install requirements --
if [ -f "$ROOT/requirements.txt" ]; then
  echo "[2/3] Installing requirements.txt ..."
  PIP="$PY -m pip"
  if ! $PY -m pip --version >/dev/null 2>&1; then
    echo "[INFO] pip not found, trying ensurepip..."
    $PY -m ensurepip --upgrade || true
  fi
  # PEP 668: on Debian 12+ need --break-system-packages or use venv
  INSTALL_CMD="$PY -m pip install -r \"$ROOT/requirements.txt\""
  if ! $PY -m pip install -r "$ROOT/requirements.txt" 2>&1; then
    echo "[INFO] Retrying with --break-system-packages (Debian/Ubuntu)..."
    $PY -m pip install --break-system-packages -r "$ROOT/requirements.txt" || \
      echo "[WARN] pip install had warnings — continuing (app runs on stdlib only)"
  else
    echo "      Done."
  fi
else
  echo "[2/3] No requirements.txt — skipping (stdlib only)"
fi
echo ""

# -- launch --
echo "[3/3] Launching..."
echo "      DB: $ROOT/expenses.db"
echo ""
exec $PY "$ROOT/expense_tracker.py"
