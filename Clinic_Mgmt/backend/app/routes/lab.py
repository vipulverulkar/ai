"""Lab test catalog and order routes (MVC: Controller).

Order lifecycle: ordered -> collected -> in_progress -> completed
(cancelled any time before completion). Completion requires a result
for every item.
"""
from datetime import datetime

from flask import Blueprint, jsonify, request

from app.models import db
from app.models.lab import LabOrder, LabOrderItem, LabTest
from app.rbac import require_admin

lab_bp = Blueprint('lab', __name__)

FLOW = {
    'ordered': ('collected', 'cancelled'),
    'collected': ('in_progress', 'cancelled'),
    'in_progress': ('completed', 'cancelled'),
    'completed': (),
    'cancelled': (),
}


@lab_bp.route('/api/lab-tests', methods=['GET'])
def get_lab_tests():
    active_only = request.args.get('active') == '1'
    query = LabTest.query
    if active_only:
        query = query.filter_by(is_active=True)
    return jsonify([t.to_dict() for t in query.order_by(LabTest.name).all()])


@lab_bp.route('/api/lab-tests/<int:id>', methods=['GET'])
def get_lab_test(id):
    return jsonify(LabTest.query.get_or_404(id).to_dict())


@lab_bp.route('/api/lab-tests', methods=['POST'])
@require_admin
def create_lab_test():
    data = request.get_json() or {}
    if not (data.get('name') or '').strip():
        return jsonify({'error': 'Test name is required'}), 400
    if LabTest.query.filter_by(name=data['name'].strip()).first():
        return jsonify({'error': 'A test with this name already exists'}), 409
    try:
        price = float(data.get('price', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid price'}), 400
    test = LabTest(
        name=data['name'].strip(),
        category=(data.get('category') or 'General').strip(),
        description=(data.get('description') or '').strip() or None,
        price=round(max(price, 0), 2),
        turnaround_hours=data.get('turnaround_hours') or 24,
        is_active=bool(data.get('is_active', True)),
    )
    db.session.add(test)
    db.session.commit()
    return jsonify(test.to_dict()), 201


@lab_bp.route('/api/lab-tests/<int:id>', methods=['PUT'])
@require_admin
def update_lab_test(id):
    test = LabTest.query.get_or_404(id)
    data = request.get_json() or {}
    if data.get('name'):
        test.name = data['name'].strip()
    for field in ('category', 'description'):
        if field in data:
            setattr(test, field, (data[field] or '').strip() or None)
    if 'price' in data:
        try:
            test.price = round(max(float(data['price']), 0), 2)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid price'}), 400
    if 'turnaround_hours' in data:
        test.turnaround_hours = data['turnaround_hours']
    if 'is_active' in data:
        test.is_active = bool(data['is_active'])
    db.session.commit()
    return jsonify(test.to_dict())


@lab_bp.route('/api/lab-tests/<int:id>', methods=['DELETE'])
@require_admin
def delete_lab_test(id):
    test = LabTest.query.get_or_404(id)
    if LabOrderItem.query.filter_by(lab_test_id=id).first():
        return jsonify({'error': 'Test is used in lab orders and cannot be deleted. Deactivate it instead.'}), 400
    db.session.delete(test)
    db.session.commit()
    return '', 204


@lab_bp.route('/api/lab-orders', methods=['GET'])
def get_lab_orders():
    query = LabOrder.query
    if request.args.get('status'):
        query = query.filter_by(status=request.args.get('status'))
    if request.args.get('patient_id'):
        query = query.filter_by(patient_id=request.args.get('patient_id'))
    orders = query.order_by(LabOrder.created_at.desc()).all()
    return jsonify([o.to_dict() for o in orders])


@lab_bp.route('/api/lab-orders/<int:id>', methods=['GET'])
def get_lab_order(id):
    return jsonify(LabOrder.query.get_or_404(id).to_dict())


@lab_bp.route('/api/lab-orders', methods=['POST'])
def create_lab_order():
    data = request.get_json() or {}
    if not data.get('patient_id'):
        return jsonify({'error': 'Patient is required'}), 400
    test_ids = data.get('test_ids') or []
    if not test_ids:
        return jsonify({'error': 'Select at least one test'}), 400
    tests = LabTest.query.filter(LabTest.id.in_(test_ids), LabTest.is_active.is_(True)).all()
    if len(tests) != len(set(test_ids)):
        return jsonify({'error': 'One or more selected tests are invalid or inactive'}), 400
    order = LabOrder(
        patient_id=data['patient_id'],
        appointment_id=data.get('appointment_id') or None,
        priority=(data.get('priority') or 'routine').strip(),
        status='ordered',
    )
    db.session.add(order)
    db.session.flush()
    for t in tests:
        db.session.add(LabOrderItem(order_id=order.id, lab_test_id=t.id, price=t.price))
    db.session.commit()
    return jsonify(order.to_dict()), 201


@lab_bp.route('/api/lab-orders/<int:id>/status', methods=['POST'])
def transition_order(id):
    order = LabOrder.query.get_or_404(id)
    data = request.get_json() or {}
    target = (data.get('status') or '').strip()
    if target not in FLOW.get(order.status, ()):
        return jsonify({'error': f'Cannot move order from {order.status} to {target or "blank"}'}), 400
    if target == 'completed':
        missing = [i.test.name if i.test else f'item {i.id}'
                   for i in order.items if not (i.result_value or '').strip()]
        if missing:
            return jsonify({'error': f'Results missing for: {", ".join(missing)}'}), 400
        order.completed_at = datetime.utcnow()
    order.status = target
    db.session.commit()
    return jsonify(order.to_dict())


@lab_bp.route('/api/lab-orders/<int:id>', methods=['DELETE'])
def delete_lab_order(id):
    order = LabOrder.query.get_or_404(id)
    if order.status not in ('ordered', 'cancelled'):
        return jsonify({'error': 'Only new or cancelled orders can be deleted'}), 400
    db.session.delete(order)
    db.session.commit()
    return '', 204


@lab_bp.route('/api/order-items/<int:id>', methods=['PUT'])
def update_order_item(id):
    item = LabOrderItem.query.get_or_404(id)
    if item.order.status in ('completed', 'cancelled'):
        return jsonify({'error': 'Results are locked for completed/cancelled orders'}), 400
    data = request.get_json() or {}
    if 'result_value' in data:
        item.result_value = (data['result_value'] or '').strip() or None
    if 'result_flag' in data:
        flag = (data['result_flag'] or '').strip().lower() or None
        if flag and flag not in ('normal', 'high', 'low', 'critical'):
            return jsonify({'error': 'Flag must be normal, high, low or critical'}), 400
        item.result_flag = flag
    if 'result_note' in data:
        item.result_note = (data['result_note'] or '').strip() or None
    db.session.commit()
    return jsonify(item.to_dict())
