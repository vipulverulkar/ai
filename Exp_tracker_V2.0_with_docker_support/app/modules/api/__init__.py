"""API module — read-only JSON endpoints (/api/summary, /api/transactions)."""
from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api")

from . import controllers  # noqa: E402,F401
