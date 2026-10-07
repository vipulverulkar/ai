"""Dashboard module — home page with summaries, trend, budgets overview."""
from flask import Blueprint

bp = Blueprint("dashboard", __name__, template_folder="templates")

from . import controllers  # noqa: E402,F401
