"""Treatment routes (MVC: Controller)."""
from flask import Blueprint, jsonify, request

from app.models import db
from app.models.treatment import Treatment

treatments_bp = Blueprint('treatments', __name__)


@treatments_bp.route('/api/treatments', methods=['GET'])
def get_treatments():
    treatments = Treatment.query.order_by(Treatment.created_at.desc()).all()
    return jsonify([t.to_dict() for t in treatments])


@treatments_bp.route('/api/treatments/<int:id>', methods=['GET'])
def get_treatment(id):
    treatment = Treatment.query.get_or_404(id)
    return jsonify(treatment.to_dict())


@treatments_bp.route('/api/treatments', methods=['POST'])
def create_treatment():
    data = request.get_json() or {}
    missing = [f for f in ('name', 'category') if not (data.get(f) or '').strip()]
    if missing:
        return jsonify({'error': f"Missing required fields: {', '.join(missing)}"}), 400
    treatment = Treatment(
        name=data.get('name'),
        category=data.get('category'),
        description=data.get('description'),
        duration_minutes=data.get('duration_minutes', 30),
        cost=data.get('cost', 0.0)
    )
    db.session.add(treatment)
    db.session.commit()
    return jsonify(treatment.to_dict()), 201


@treatments_bp.route('/api/treatments/<int:id>', methods=['PUT'])
def update_treatment(id):
    treatment = Treatment.query.get_or_404(id)
    data = request.get_json() or {}
    treatment.name = data.get('name', treatment.name)
    treatment.category = data.get('category', treatment.category)
    treatment.description = data.get('description', treatment.description)
    treatment.duration_minutes = data.get('duration_minutes', treatment.duration_minutes)
    treatment.cost = data.get('cost', treatment.cost)
    db.session.commit()
    return jsonify(treatment.to_dict())


@treatments_bp.route('/api/treatments/<int:id>', methods=['DELETE'])
def delete_treatment(id):
    treatment = Treatment.query.get_or_404(id)
    db.session.delete(treatment)
    db.session.commit()
    return '', 204
