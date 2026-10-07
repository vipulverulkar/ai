"""Auth module — single-user session login."""
from flask import Blueprint

bp = Blueprint("auth", __name__, template_folder="templates")

from . import controllers  # noqa: E402,F401
