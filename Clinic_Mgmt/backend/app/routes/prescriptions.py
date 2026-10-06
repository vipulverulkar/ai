"""Prescription routes (MVC: Controller)."""
from flask import Blueprint, jsonify, request

from app.models import db
from app.models.appointment import Appointment
from app.models.prescription import Prescription

prescriptions_bp = Blueprint('prescriptions', __name__)


@prescriptions_bp.route('/api/appointments/<int:appointment_id>/prescriptions', methods=['GET'])
def get_prescriptions(appointment_id):
    Appointment.query.get_or_404(appointment_id)
    items = Prescription.query.filter_by(appointment_id=appointment_id).order_by(Prescription.id).all()
    return jsonify([i.to_dict() for i in items])


@prescriptions_bp.route('/api/appointments/<int:appointment_id>/prescriptions', methods=['POST'])
def create_prescription(appointment_id):
    Appointment.query.get_or_404(appointment_id)
    data = request.get_json() or {}
    if not (data.get('medicine') or '').strip():
        return jsonify({'error': 'Medicine name is required'}), 400
    item = Prescription(
        appointment_id=appointment_id,
        medicine=data['medicine'].strip(),
        dosage=(data.get('dosage') or '').strip() or None,
        frequency=(data.get('frequency') or '').strip() or None,
        duration_days=data.get('duration_days'),
        instructions=(data.get('instructions') or '').strip() or None,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@prescriptions_bp.route('/api/prescriptions/<int:id>', methods=['PUT'])
def update_prescription(id):
    item = Prescription.query.get_or_404(id)
    data = request.get_json() or {}
    for field in ('medicine', 'dosage', 'frequency', 'instructions'):
        if data.get(field) is not None:
            item.__setattr__(field, data[field].strip() or None)
    if 'duration_days' in data:
        item.duration_days = data['duration_days']
    db.session.commit()
    return jsonify(item.to_dict())


@prescriptions_bp.route('/api/prescriptions/<int:id>', methods=['DELETE'])
def delete_prescription(id):
    db.session.delete(Prescription.query.get_or_404(id))
    db.session.commit()
    return '', 204
