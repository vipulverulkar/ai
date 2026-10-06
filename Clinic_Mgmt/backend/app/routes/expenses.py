"""Expense routes (MVC: Controller)."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from app.models import db
from app.models.expense import Expense
from app.rbac import require_admin

expenses_bp = Blueprint('expenses', __name__)


@expenses_bp.route('/api/expenses', methods=['GET'])
@require_admin
def get_expenses():
    category = request.args.get('category')
    query = Expense.query
    if category:
        query = query.filter_by(category=category)
    rows = query.order_by(Expense.expense_date.desc()).all()
    return jsonify([e.to_dict() for e in rows])


@expenses_bp.route('/api/expenses', methods=['POST'])
@require_admin
def create_expense():
    data = request.get_json() or {}
    if not (data.get('title') or '').strip():
        return jsonify({'error': 'Title is required'}), 400
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid amount'}), 400
    if amount <= 0:
        return jsonify({'error': 'Amount must be positive'}), 400
    exp_date = None
    if data.get('expense_date'):
        try:
            exp_date = datetime.strptime(data['expense_date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'expense_date must be YYYY-MM-DD'}), 400
    expense = Expense(
        title=data['title'].strip(),
        category=(data.get('category') or 'General').strip(),
        amount=round(amount, 2),
        expense_date=exp_date or datetime.utcnow().date(),
        note=(data.get('note') or '').strip() or None,
    )
    db.session.add(expense)
    db.session.commit()
    return jsonify(expense.to_dict()), 201


@expenses_bp.route('/api/expenses/<int:id>', methods=['DELETE'])
@require_admin
def delete_expense(id):
    db.session.delete(Expense.query.get_or_404(id))
    db.session.commit()
    return '', 204
