"""Doctor routes (MVC: Controller)."""
from flask import Blueprint, jsonify, request

from app.models import db
from app.models.doctor import Doctor

doctors_bp = Blueprint('doctors', __name__)


@doctors_bp.route('/api/doctors', methods=['GET'])
def get_doctors():
    doctors = Doctor.query.order_by(Doctor.created_at.desc()).all()
    return jsonify([d.to_dict() for d in doctors])


@doctors_bp.route('/api/doctors/<int:id>', methods=['GET'])
def get_doctor(id):
    doctor = Doctor.query.get_or_404(id)
    return jsonify(doctor.to_dict())


@doctors_bp.route('/api/doctors', methods=['POST'])
def create_doctor():
    data = request.get_json() or {}
    missing = [f for f in ('name', 'specialization', 'phone') if not (data.get(f) or '').strip()]
    if missing:
        return jsonify({'error': f"Missing required fields: {', '.join(missing)}"}), 400
    doctor = Doctor(
        name=data.get('name'),
        specialization=data.get('specialization'),
        phone=data.get('phone'),
        email=data.get('email'),
        experience_years=data.get('experience_years', 0),
        consultation_fee=data.get('consultation_fee', 0.0),
        qualification=data.get('qualification'),
        bio=data.get('bio')
    )
    db.session.add(doctor)
    db.session.commit()
    return jsonify(doctor.to_dict()), 201


@doctors_bp.route('/api/doctors/<int:id>', methods=['PUT'])
def update_doctor(id):
    doctor = Doctor.query.get_or_404(id)
    data = request.get_json() or {}
    doctor.name = data.get('name', doctor.name)
    doctor.specialization = data.get('specialization', doctor.specialization)
    doctor.phone = data.get('phone', doctor.phone)
    doctor.email = data.get('email', doctor.email)
    doctor.experience_years = data.get('experience_years', doctor.experience_years)
    doctor.consultation_fee = data.get('consultation_fee', doctor.consultation_fee)
    doctor.qualification = data.get('qualification', doctor.qualification)
    doctor.bio = data.get('bio', doctor.bio)
    db.session.commit()
    return jsonify(doctor.to_dict())


@doctors_bp.route('/api/doctors/<int:id>', methods=['DELETE'])
def delete_doctor(id):
    doctor = Doctor.query.get_or_404(id)
    db.session.delete(doctor)
    db.session.commit()
    return '', 204
