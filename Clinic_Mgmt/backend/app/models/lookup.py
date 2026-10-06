"""Lookup models (MVC: Model). Master data for UI dropdowns."""
from datetime import datetime

from app.models import db


class Lookup(db.Model):
    """Generic master-data table: dropdown values previously hardcoded in the UI."""
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False, index=True)
    value = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('type', 'value', name='uq_lookup_type_value'),)

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'value': self.value,
            'is_active': self.is_active,
            'sort_order': self.sort_order
        }


class LookupType(db.Model):
    """Metadata for each master-data type: display label, icon, help text.
    Lets admins rename/relabel master sections without code changes."""
    type = db.Column(db.String(50), primary_key=True)
    label = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(50), default='bi-tags')
    description = db.Column(db.String(200), default='')
    placeholder = db.Column(db.String(100), default='')
    has_form = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            'type': self.type,
            'label': self.label,
            'icon': self.icon,
            'description': self.description,
            'placeholder': self.placeholder,
            'has_form': self.has_form,
            'sort_order': self.sort_order
        }
