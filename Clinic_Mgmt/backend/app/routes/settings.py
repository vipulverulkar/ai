"""Clinic settings routes (MVC: Controller)."""
from flask import Blueprint, jsonify, request

from app.models import db
from app.models.setting import Setting
from app.rbac import require_admin
from app.seed import DEFAULT_SETTINGS

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/api/settings', methods=['GET'])
def get_settings():
    rows = Setting.query.all()
    data = {r.key: r.value for r in rows}
    for key, default in DEFAULT_SETTINGS.items():
        data.setdefault(key, default)
    return jsonify(data)


@settings_bp.route('/api/settings', methods=['PUT'])
@require_admin
def update_settings():
    data = request.get_json() or {}
    for key, value in data.items():
        if not isinstance(key, str) or len(key) > 80 or key.startswith('_'):
            continue
        row = db.session.get(Setting, key)
        if row is None:
            row = Setting(key=key, value='')
            db.session.add(row)
        row.value = '' if value is None else str(value)[:500]
    db.session.commit()
    return jsonify({r.key: r.value for r in Setting.query.all()})
