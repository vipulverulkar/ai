"""Lab models (MVC: Model). Test catalog + orders with results."""
from datetime import datetime

from app.models import db


class LabTest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    category = db.Column(db.String(50), nullable=False, default='General')
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False, default=0.0)
    turnaround_hours = db.Column(db.Integer, default=24)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'description': self.description,
            'price': self.price,
            'turnaround_hours': self.turnaround_hours,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class LabOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'))
    priority = db.Column(db.String(20), default='routine')
    status = db.Column(db.String(20), default='ordered')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    patient = db.relationship('Patient', backref='lab_orders')
    appointment = db.relationship('Appointment', backref='lab_orders')
    items = db.relationship('LabOrderItem', backref='order', cascade='all, delete-orphan',
                            order_by='LabOrderItem.id')

    @property
    def total(self):
        return round(sum((i.price or 0) for i in self.items), 2)

    def to_dict(self):
        return {
            'id': self.id,
            'order_no': f'LO-{self.id:04d}',
            'patient_id': self.patient_id,
            'patient_name': self.patient.name if self.patient else None,
            'appointment_id': self.appointment_id,
            'priority': self.priority,
            'status': self.status,
            'total': self.total,
            'items': [i.to_dict() for i in self.items],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class LabOrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('lab_order.id'), nullable=False)
    lab_test_id = db.Column(db.Integer, db.ForeignKey('lab_test.id'), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0.0)
    result_value = db.Column(db.String(200))
    result_flag = db.Column(db.String(20))
    result_note = db.Column(db.String(200))

    test = db.relationship('LabTest')

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'lab_test_id': self.lab_test_id,
            'test_name': self.test.name if self.test else None,
            'price': self.price,
            'result_value': self.result_value,
            'result_flag': self.result_flag,
            'result_note': self.result_note,
        }
