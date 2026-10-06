"""Bill and payment routes (MVC: Controller)."""
from flask import Blueprint, jsonify, request

from app.models import db
from app.models.appointment import Appointment
from app.models.bill import Bill, Payment
from app.rbac import require_admin
from app.seed import get_setting

bills_bp = Blueprint('bills', __name__)


def _bill_payload(bill):
    return bill.to_dict(invoice_prefix=get_setting('invoice_prefix', 'INV'))


@bills_bp.route('/api/bills', methods=['GET'])
def get_bills():
    status = request.args.get('status')
    query = Bill.query
    if status:
        query = query.filter_by(status=status)
    bills = query.order_by(Bill.created_at.desc()).all()
    return jsonify([_bill_payload(b) for b in bills])


@bills_bp.route('/api/bills/<int:id>', methods=['GET'])
def get_bill(id):
    return jsonify(_bill_payload(Bill.query.get_or_404(id)))


@bills_bp.route('/api/bills', methods=['POST'])
def create_bill():
    """Generate a bill from an appointment, snapshotting current prices + tax."""
    data = request.get_json() or {}
    try:
        appointment_id = int(data.get('appointment_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Valid appointment_id is required'}), 400
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.bill is not None:
        return jsonify({'error': 'Bill already exists for this appointment',
                        'bill': _bill_payload(appointment.bill)}), 409
    try:
        tax_percent = float(get_setting('tax_percent', '0') or 0)
    except ValueError:
        tax_percent = 0.0
    treatment_cost = appointment.treatment.cost if appointment.treatment else 0.0
    consultation_fee = appointment.doctor.consultation_fee if appointment.doctor else 0.0
    subtotal = (treatment_cost or 0) + (consultation_fee or 0)
    tax_amount = round(subtotal * tax_percent / 100, 2)
    bill = Bill(
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        doctor_id=appointment.doctor_id,
        treatment_id=appointment.treatment_id,
        treatment_cost=treatment_cost or 0.0,
        consultation_fee=consultation_fee or 0.0,
        tax_percent=tax_percent,
        tax_amount=tax_amount,
        total=round(subtotal + tax_amount, 2),
        amount_paid=0.0,
        status='unpaid',
    )
    db.session.add(bill)
    db.session.commit()
    return jsonify(_bill_payload(bill)), 201


@bills_bp.route('/api/bills/<int:id>/payments', methods=['POST'])
def record_payment(id):
    bill = Bill.query.get_or_404(id)
    data = request.get_json() or {}
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid amount'}), 400
    if amount <= 0:
        return jsonify({'error': 'Amount must be positive'}), 400
    if round(bill.amount_paid + amount - bill.total, 2) > 0:
        return jsonify({'error': f'Payment exceeds balance of {bill.balance:.2f}'}), 400
    payment = Payment(bill_id=bill.id, amount=round(amount, 2),
                      method=(data.get('method') or 'Cash').strip(),
                      note=(data.get('note') or '').strip() or None)
    bill.amount_paid = round(bill.amount_paid + payment.amount, 2)
    bill.refresh_status()
    db.session.add(payment)
    db.session.commit()
    return jsonify(_bill_payload(bill)), 201


@bills_bp.route('/api/bills/<int:id>/discount', methods=['POST'])
@require_admin
def apply_discount(id):
    bill = Bill.query.get_or_404(id)
    if bill.status == 'cancelled':
        return jsonify({'error': 'Bill is cancelled'}), 400
    if bill.amount_paid > 0:
        return jsonify({'error': 'Cannot discount a bill with payments recorded'}), 400
    data = request.get_json() or {}
    try:
        discount = float(data.get('discount_amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid discount amount'}), 400
    if discount < 0:
        return jsonify({'error': 'Discount cannot be negative'}), 400
    bill.apply_discount(discount)
    db.session.commit()
    return jsonify(_bill_payload(bill))


@bills_bp.route('/api/bills/<int:id>/void', methods=['POST'])
@require_admin
def void_bill(id):
    bill = Bill.query.get_or_404(id)
    if bill.amount_paid > 0:
        return jsonify({'error': 'Cannot void a bill with payments. Record a refund instead.'}), 400
    bill.status = 'cancelled'
    db.session.commit()
    return jsonify(_bill_payload(bill))
