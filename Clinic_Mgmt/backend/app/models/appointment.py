"""Appointment model (MVC: Model). Links patient + doctor + treatment."""
from datetime import datetime

from app.models import db


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=False)
    treatment_id = db.Column(db.Integer, db.ForeignKey('treatment.id'), nullable=False)
    appointment_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='pending')
    token_no = db.Column(db.Integer)
    notes = db.Column(db.Text)
    chief_complaint = db.Column(db.Text)
    diagnosis = db.Column(db.Text)
    vitals_bp = db.Column(db.String(20))
    vitals_sugar = db.Column(db.String(20))
    vitals_weight = db.Column(db.String(20))
    vitals_temp = db.Column(db.String(20))
    follow_up_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship('Patient', backref='appointments')
    doctor = db.relationship('Doctor', backref='appointments')
    treatment = db.relationship('Treatment', backref='appointments')

    def to_dict(self):
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'patient_name': self.patient.name if self.patient else None,
            'doctor_id': self.doctor_id,
            'doctor_name': self.doctor.name if self.doctor else None,
            'treatment_id': self.treatment_id,
            'treatment_name': self.treatment.name if self.treatment else None,
            'treatment_cost': self.treatment.cost if self.treatment else None,
            'appointment_date': self.appointment_date.isoformat() if self.appointment_date else None,
            'status': self.status,
            'token_no': self.token_no,
            'notes': self.notes,
            'chief_complaint': self.chief_complaint,
            'diagnosis': self.diagnosis,
            'vitals_bp': self.vitals_bp,
            'vitals_sugar': self.vitals_sugar,
            'vitals_weight': self.vitals_weight,
            'vitals_temp': self.vitals_temp,
            'follow_up_date': self.follow_up_date.isoformat() if self.follow_up_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
