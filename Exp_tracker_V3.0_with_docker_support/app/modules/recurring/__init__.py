"""Recurring transactions module — auto-generate transactions on a schedule."""
from flask import Blueprint

bp = Blueprint("recurring", __name__, template_folder="templates")

from . import controllers  # noqa: E402,F401
