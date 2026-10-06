"""Expense model (MVC: Model). Clinic running costs for profit reporting."""
from datetime import datetime

from app.models import db


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='General')
    amount = db.Column(db.Float, nullable=False, default=0.0)
    expense_date = db.Column(db.Date, default=datetime.utcnow)
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'category': self.category,
            'amount': self.amount,
            'expense_date': self.expense_date.isoformat() if self.expense_date else None,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
