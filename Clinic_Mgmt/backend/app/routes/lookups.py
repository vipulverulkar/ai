"""Lookup (master data) routes (MVC: Controller)."""
from flask import Blueprint, jsonify, request

from app.models import db
from app.models.appointment import Appointment
from app.models.bill import Payment
from app.models.doctor import Doctor
from app.models.lookup import Lookup, LookupType
from app.models.patient import Patient
from app.models.treatment import Treatment
from app.models.user import User
from app.rbac import require_admin

lookups_bp = Blueprint('lookups', __name__)

# Lookup type -> (model, column) holding live references. Deleting an
# in-use value is blocked; deactivating it remains allowed.
REFERENCES = {
    'specialization': (Doctor, 'specialization'),
    'treatment_category': (Treatment, 'category'),
    'appointment_status': (Appointment, 'status'),
    'gender': (Patient, 'gender'),
    'blood_group': (Patient, 'blood_group'),
    'user_role': (User, 'role'),
    'payment_method': (Payment, 'method'),
}


@lookups_bp.route('/api/lookup-types', methods=['GET'])
def get_lookup_types():
    types = LookupType.query.order_by(LookupType.sort_order, LookupType.type).all()
    return jsonify([t.to_dict() for t in types])


@lookups_bp.route('/api/lookup-types/<string:lookup_type>', methods=['PUT'])
@require_admin
def update_lookup_type(lookup_type):
    item = LookupType.query.get_or_404(lookup_type)
    data = request.get_json() or {}
    for field in ('label', 'icon', 'description', 'placeholder'):
        if data.get(field) is not None:
            setattr(item, field, data[field])
    if 'has_form' in data:
        item.has_form = bool(data['has_form'])
    if 'sort_order' in data:
        item.sort_order = data['sort_order']
    db.session.commit()
    return jsonify(item.to_dict())


@lookups_bp.route('/api/lookups', methods=['GET'])
def get_lookups():
    lookup_type = request.args.get('type')
    query = Lookup.query
    if lookup_type:
        query = query.filter_by(type=lookup_type)
    lookups = query.order_by(Lookup.type, Lookup.sort_order, Lookup.id).all()
    return jsonify([l.to_dict() for l in lookups])


@lookups_bp.route('/api/lookups/<int:id>', methods=['GET'])
def get_lookup(id):
    return jsonify(Lookup.query.get_or_404(id).to_dict())


@lookups_bp.route('/api/lookups', methods=['POST'])
@require_admin
def create_lookup():
    data = request.get_json() or {}
    lookup_type = (data.get('type') or '').strip()
    value = (data.get('value') or '').strip()
    if not lookup_type or not value:
        return jsonify({'error': 'Type and value are required'}), 400
    if Lookup.query.filter_by(type=lookup_type, value=value).first():
        return jsonify({'error': 'This value already exists'}), 409
    lookup = Lookup(type=lookup_type, value=value,
                    is_active=data.get('is_active', True),
                    sort_order=data.get('sort_order', 0))
    db.session.add(lookup)
    db.session.commit()
    return jsonify(lookup.to_dict()), 201


@lookups_bp.route('/api/lookups/<int:id>', methods=['PUT'])
@require_admin
def update_lookup(id):
    lookup = Lookup.query.get_or_404(id)
    data = request.get_json() or {}
    if data.get('value'):
        lookup.value = data['value'].strip()
    if 'is_active' in data:
        lookup.is_active = bool(data['is_active'])
    if 'sort_order' in data:
        lookup.sort_order = data['sort_order']
    db.session.commit()
    return jsonify(lookup.to_dict())


@lookups_bp.route('/api/lookups/<int:id>', methods=['DELETE'])
@require_admin
def delete_lookup(id):
    lookup = Lookup.query.get_or_404(id)
    ref = REFERENCES.get(lookup.type)
    if ref is not None:
        model, field = ref
        if model.query.filter(getattr(model, field) == lookup.value).first() is not None:
            return jsonify({'error': f"'{lookup.value}' is in use and cannot be deleted. Deactivate it instead."}), 400
    db.session.delete(lookup)
    db.session.commit()
    return '', 204
