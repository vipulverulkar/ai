"""Audit trail routes (MVC: Controller)."""
from flask import Blueprint, jsonify, request

from app.models.setting import AuditLog
from app.rbac import require_admin

audit_bp = Blueprint('audit', __name__)


@audit_bp.route('/api/audit', methods=['GET'])
@require_admin
def get_audit():
    entity = request.args.get('entity')
    action = request.args.get('action')
    try:
        limit = min(int(request.args.get('limit', 100)), 500)
    except ValueError:
        limit = 100
    query = AuditLog.query
    if entity:
        query = query.filter_by(entity=entity)
    if action:
        query = query.filter_by(action=action)
    rows = query.order_by(AuditLog.id.desc()).limit(limit).all()
    return jsonify([r.to_dict() for r in rows])
