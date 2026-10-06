"""Prescription item model (MVC: Model). One row per medicine prescribed."""
from datetime import datetime

from app.models import db


class Prescription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False)
    medicine = db.Column(db.String(100), nullable=False)
    dosage = db.Column(db.String(50))
    frequency = db.Column(db.String(50))
    duration_days = db.Column(db.Integer)
    instructions = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    appointment = db.relationship('Appointment', backref='prescriptions')

    def to_dict(self):
        return {
            'id': self.id,
            'appointment_id': self.appointment_id,
            'medicine': self.medicine,
            'dosage': self.dosage,
            'frequency': self.frequency,
            'duration_days': self.duration_days,
            'instructions': self.instructions,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
