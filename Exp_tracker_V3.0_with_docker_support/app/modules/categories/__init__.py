"""Categories module — manage income/expense categories."""
from flask import Blueprint

bp = Blueprint("categories", __name__, template_folder="templates")

from . import controllers  # noqa: E402,F401
