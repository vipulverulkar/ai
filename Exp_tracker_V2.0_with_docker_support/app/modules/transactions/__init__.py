"""Transactions module — list/filter/sort/paginate, CRUD, CSV import/export."""
from flask import Blueprint

bp = Blueprint("transactions", __name__, template_folder="templates")

from . import controllers  # noqa: E402,F401
