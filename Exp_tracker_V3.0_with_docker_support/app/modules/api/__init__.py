"""API module — read-only JSON endpoints.

Two mounted versions share the same handlers:
- /api/...      legacy (kept for backward compatibility)
- /api/v1/...   versioned — preferred for programmatic clients
"""
from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api")
bp_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")

from . import controllers  # noqa: E402,F401
