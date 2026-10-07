"""Data module — full-dataset CSV import (categories + budgets + transactions)."""
from flask import Blueprint

bp = Blueprint("data", __name__, template_folder="templates")

from . import controllers  # noqa: E402,F401
