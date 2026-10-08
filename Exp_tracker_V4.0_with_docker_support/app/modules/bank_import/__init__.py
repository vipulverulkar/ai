from flask import Blueprint

bp = Blueprint("bank_import", __name__, url_prefix="/bank-import")

from .controllers import *
