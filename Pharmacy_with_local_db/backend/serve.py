"""Windows-friendly production server: migrate, then serve with waitress.

Run from the ``backend/`` directory (``start.bat`` does this)::

    python serve.py

Uses ``PORT`` / ``ADMIN_USER`` / ``ADMIN_PASS`` / ``SESSION_HOURS`` /
``DATABASE_URL`` from the environment, same as ``app.py``.
"""

import os

from app import ADMIN_PASS, ADMIN_USER, app, engine, migrate

if __name__ == "__main__":
    applied = migrate(engine, ADMIN_USER, ADMIN_PASS)
    if applied:
        print(f"Applied migrations: {applied}")
    port = int(os.environ.get("PORT", "5000"))
    print(f"Serving at http://127.0.0.1:{port}/ (login: admin / admin)")
    from waitress import serve

    serve(app, host="127.0.0.1", port=port)
