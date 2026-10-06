"""Global search across entities (MVC: Controller)."""
from flask import Blueprint, jsonify, request

from app.models.bill import Bill
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.treatment import Treatment
from app.seed import get_setting

search_bp = Blueprint('search', __name__)


@search_bp.route('/api/search', methods=['GET'])
def search():
    q = (request.args.get('q') or '').strip()
    empty = {'patients': [], 'doctors': [], 'treatments': [], 'bills': []}
    if len(q) < 2:
        return jsonify(empty)
    like = f'%{q}%'
    patients = Patient.query.filter(
        Patient.name.ilike(like) | Patient.phone.ilike(like)).limit(5).all()
    doctors = Doctor.query.filter(
        Doctor.name.ilike(like) | Doctor.specialization.ilike(like)).limit(5).all()
    treatments = Treatment.query.filter(Treatment.name.ilike(like)).limit(5).all()
    bills = Bill.query.join(Patient).filter(
        Patient.name.ilike(like)).order_by(Bill.id.desc()).limit(5).all()
    prefix = get_setting('invoice_prefix', 'INV')
    return jsonify({
        'patients': [{'id': p.id, 'uhid': p.to_dict()['uhid'], 'name': p.name, 'phone': p.phone} for p in patients],
        'doctors': [{'id': d.id, 'name': d.name, 'specialization': d.specialization} for d in doctors],
        'treatments': [{'id': t.id, 'name': t.name, 'cost': t.cost} for t in treatments],
        'bills': [{'id': b.id, 'bill_no': b.to_dict(prefix)['bill_no'], 'patient_name': b.patient.name if b.patient else None, 'total': b.total, 'status': b.status} for b in bills],
    })
