"""Auth routes (MVC: Controller)."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from app.audit import log_action
from app.models import db
from app.models.setting import LoginAttempt
from app.models.user import User
from app.seed import default_lookup_value, get_int_setting

auth_bp = Blueprint('auth', __name__)


def _limited(ip):
    max_attempts = get_int_setting('rate_limit_max_attempts', 5)
    window = timedelta(minutes=get_int_setting('rate_limit_window_minutes', 5))
    cutoff = datetime.utcnow() - window
    LoginAttempt.query.filter(LoginAttempt.attempted_at < cutoff).delete()
    db.session.commit()
    return LoginAttempt.query.filter_by(ip=ip).filter(
        LoginAttempt.attempted_at >= cutoff).count() >= max_attempts


@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    min_length = get_int_setting('password_min_length', 8)
    if len(password) < min_length:
        return jsonify({'error': f'Password must be at least {min_length} characters'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 409
    user = User(username=username,
                password_hash=generate_password_hash(password),
                role=data.get('role') or default_lookup_value('user_role') or 'staff')
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    ip = request.remote_addr or 'unknown'
    if _limited(ip):
        return jsonify({'error': 'Too many failed attempts. Try again later.'}), 429
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, data.get('password') or ''):
        db.session.add(LoginAttempt(ip=ip))
        db.session.commit()
        return jsonify({'error': 'Invalid username or password'}), 401
    LoginAttempt.query.filter_by(ip=ip).delete()
    db.session.commit()
    log_action('login', 'user', user.id, f'Login by {user.username}')
    return jsonify(user.to_dict())
