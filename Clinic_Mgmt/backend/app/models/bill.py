"""Bill and Payment models (MVC: Model). Prices are snapshotted at billing time."""
from datetime import datetime

from app.models import db


class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), unique=True, nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=False)
    treatment_id = db.Column(db.Integer, db.ForeignKey('treatment.id'), nullable=False)
    treatment_cost = db.Column(db.Float, nullable=False, default=0.0)
    consultation_fee = db.Column(db.Float, nullable=False, default=0.0)
    discount_amount = db.Column(db.Float, nullable=False, default=0.0)
    tax_percent = db.Column(db.Float, nullable=False, default=0.0)
    tax_amount = db.Column(db.Float, nullable=False, default=0.0)
    total = db.Column(db.Float, nullable=False, default=0.0)
    amount_paid = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(20), default='unpaid')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    appointment = db.relationship('Appointment', backref=db.backref('bill', uselist=False))
    patient = db.relationship('Patient', backref='bills')
    doctor = db.relationship('Doctor', backref='bills')
    treatment = db.relationship('Treatment', backref='bills')
    payments = db.relationship('Payment', backref='bill', cascade='all, delete-orphan',
                               order_by='Payment.created_at')

    @property
    def balance(self):
        return round(self.total - self.amount_paid, 2)

    def refresh_status(self):
        if self.status == 'cancelled':
            return
        if self.amount_paid >= self.total:
            self.status = 'paid'
        elif self.amount_paid > 0:
            self.status = 'partial'
        else:
            self.status = 'unpaid'

    def apply_discount(self, discount):
        subtotal = (self.treatment_cost or 0) + (self.consultation_fee or 0)
        discount = max(0.0, min(discount, subtotal))
        taxable = subtotal - discount
        self.discount_amount = round(discount, 2)
        self.tax_amount = round(taxable * (self.tax_percent or 0) / 100, 2)
        self.total = round(taxable + self.tax_amount, 2)
        self.refresh_status()

    def to_dict(self, invoice_prefix='INV'):
        return {
            'id': self.id,
            'bill_no': f'{invoice_prefix}-{self.id:04d}',
            'appointment_id': self.appointment_id,
            'patient_id': self.patient_id,
            'patient_name': self.patient.name if self.patient else None,
            'doctor_id': self.doctor_id,
            'doctor_name': self.doctor.name if self.doctor else None,
            'treatment_id': self.treatment_id,
            'treatment_name': self.treatment.name if self.treatment else None,
            'treatment_cost': self.treatment_cost,
            'consultation_fee': self.consultation_fee,
            'discount_amount': self.discount_amount,
            'tax_percent': self.tax_percent,
            'tax_amount': self.tax_amount,
            'total': self.total,
            'amount_paid': self.amount_paid,
            'balance': self.balance,
            'status': self.status,
            'payments': [p.to_dict() for p in self.payments],
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bill.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(30), nullable=False, default='Cash')
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'bill_id': self.bill_id,
            'amount': self.amount,
            'method': self.method,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
