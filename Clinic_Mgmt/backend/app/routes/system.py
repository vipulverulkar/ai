"""System routes such as health checks (MVC: Controller)."""
from flask import Blueprint, jsonify

system_bp = Blueprint('system', __name__)


@system_bp.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'clinic-api'})
