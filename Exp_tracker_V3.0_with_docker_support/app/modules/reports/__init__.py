"""Reports module — daily/monthly income-expense-savings summaries."""
from flask import Blueprint

bp = Blueprint("reports", __name__, template_folder="templates")

from . import controllers  # noqa: E402,F401
