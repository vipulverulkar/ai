"""Role-based access control (MVC: middleware).

The frontend identifies the caller via X-User; the role is resolved here
from the users table so API-level enforcement cannot be bypassed by
editing templates. Requires the shared X-API-Key (checked separately).
"""
from functools import wraps

from flask import g, jsonify

from app.models.user import User


def current_role():
    actor = getattr(g, 'actor', None)
    if not actor or actor in ('system', 'anonymous'):
        return None
    user = User.query.filter_by(username=actor).first()
    return user.role if user else None


def require_roles(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if current_role() not in roles:
                return jsonify({'error': 'Forbidden: insufficient role'}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


require_admin = require_roles('admin')
