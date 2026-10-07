"""Budgets module — monthly spending limits per expense category."""
from flask import Blueprint

bp = Blueprint("budgets", __name__, template_folder="templates")

from . import controllers  # noqa: E402,F401
