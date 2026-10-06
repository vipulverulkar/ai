"""Setting and AuditLog models (MVC: Model)."""
from datetime import datetime

from app.models import db


class Setting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(500), nullable=False, default='')

    def to_dict(self):
        return {'key': self.key, 'value': self.value}


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(80), nullable=False, default='system')
    action = db.Column(db.String(30), nullable=False)
    entity = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.String(50))
    detail = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'actor': self.actor,
            'action': self.action,
            'entity': self.entity,
            'entity_id': self.entity_id,
            'detail': self.detail,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class LoginAttempt(db.Model):
    """Failed login attempts per IP for DB-backed rate limiting."""
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(45), nullable=False, index=True)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)
