"""User management routes (MVC: Controller)."""
from flask import Blueprint, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import db
from app.models.user import User
from app.rbac import require_admin
from app.seed import get_int_setting

users_bp = Blueprint('users', __name__)


@users_bp.route('/api/users', methods=['GET'])
@require_admin
def get_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([u.to_dict() for u in users])


@users_bp.route('/api/users/<int:id>', methods=['GET'])
@require_admin
def get_user(id):
    return jsonify(User.query.get_or_404(id).to_dict())


@users_bp.route('/api/users/<int:id>', methods=['PUT'])
@require_admin
def update_user(id):
    user = User.query.get_or_404(id)
    data = request.get_json() or {}
    if data.get('username'):
        new_username = data['username'].strip()
        existing = User.query.filter_by(username=new_username).first()
        if existing and existing.id != user.id:
            return jsonify({'error': 'Username already exists'}), 409
        user.username = new_username
    if data.get('role'):
        if user.role == 'admin' and data['role'] != 'admin':
            admin_count = User.query.filter_by(role='admin').count()
            if admin_count <= 1:
                return jsonify({'error': 'Cannot demote the last admin user'}), 400
        user.role = data['role']
    if data.get('password'):
        min_length = get_int_setting('password_min_length', 8)
        if len(data['password']) < min_length:
            return jsonify({'error': f'Password must be at least {min_length} characters'}), 400
        user.password_hash = generate_password_hash(data['password'])
    db.session.commit()
    return jsonify(user.to_dict())


@users_bp.route('/api/users/<int:id>', methods=['DELETE'])
@require_admin
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.role == 'admin' and User.query.filter_by(role='admin').count() <= 1:
        return jsonify({'error': 'Cannot delete the last admin user'}), 400
    db.session.delete(user)
    db.session.commit()
    return '', 204


@users_bp.route('/api/users/<int:id>/password', methods=['PUT'])
def change_password(id):
    user = User.query.get_or_404(id)
    data = request.get_json() or {}
    is_self = str(getattr(g, 'actor', '')) == user.username
    is_admin = getattr(g, 'role', None) == 'admin' and not is_self
    if not (is_self or is_admin):
        return jsonify({'error': 'Forbidden: insufficient role'}), 403
    if not is_admin:
        if not check_password_hash(user.password_hash, data.get('current_password') or ''):
            return jsonify({'error': 'Current password is incorrect'}), 401
    new_password = data.get('new_password') or ''
    min_length = get_int_setting('password_min_length', 8)
    if len(new_password) < min_length:
        return jsonify({'error': f'Password must be at least {min_length} characters'}), 400
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    return jsonify(user.to_dict())
