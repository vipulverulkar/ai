#!/bin/bash
# Dev runner: backend on :5000. Frontend needs Node; use `cd frontend && npm install && npm run dev`.
set -e
cd "$(dirname "$0")/backend"
pip install -r requirements.txt
python3 app.py
