"""Business reports (MVC: Controller). JSON + CSV for revenue and appointments."""
import csv
import io
from datetime import datetime

from flask import Blueprint, Response, jsonify, request

from app.models.appointment import Appointment
from app.models.bill import Bill
from app.models.expense import Expense
from app.models.patient import Patient
from app.rbac import require_admin

reports_bp = Blueprint('reports', __name__)


def _parse_range():
    fmt = '%Y-%m-%d'
    start = end = None
    if request.args.get('from'):
        start = datetime.strptime(request.args.get('from'), fmt)
    if request.args.get('to'):
        end = datetime.strptime(request.args.get('to'), fmt).replace(hour=23, minute=59, second=59)
    return start, end


def revenue_data():
    start, end = _parse_range()
    query = Bill.query.filter(Bill.status != 'cancelled')
    if start:
        query = query.filter(Bill.created_at >= start)
    if end:
        query = query.filter(Bill.created_at <= end)
    bills = query.all()
    total_billed = round(sum(b.total for b in bills), 2)
    collected = round(sum(b.amount_paid for b in bills), 2)
    by_status = {}
    by_day = {}
    by_treatment = {}
    by_method = {}
    for b in bills:
        by_status[b.status] = round(by_status.get(b.status, 0) + b.total, 2)
        day = b.created_at.date().isoformat() if b.created_at else 'unknown'
        d = by_day.setdefault(day, {'billed': 0.0, 'collected': 0.0})
        d['billed'] = round(d['billed'] + b.total, 2)
        d['collected'] = round(d['collected'] + b.amount_paid, 2)
        tname = b.treatment.name if b.treatment else 'Unknown'
        by_treatment[tname] = round(by_treatment.get(tname, 0) + b.total, 2)
        for p in b.payments:
            m = p.method or 'Unknown'
            by_method[m] = round(by_method.get(m, 0) + p.amount, 2)
    return {
        'from': request.args.get('from'),
        'to': request.args.get('to'),
        'bill_count': len(bills),
        'total_billed': total_billed,
        'total_collected': collected,
        'outstanding': round(total_billed - collected, 2),
        'by_status': by_status,
        'by_day': [{'date': k, **v} for k, v in sorted(by_day.items())],
        'by_treatment': by_treatment,
        'by_method': by_method,
    }


def appointments_data():
    start, end = _parse_range()
    query = Appointment.query
    if start:
        query = query.filter(Appointment.appointment_date >= start)
    if end:
        query = query.filter(Appointment.appointment_date <= end)
    appointments = query.all()
    by_status = {}
    by_doctor = {}
    by_treatment = {}
    for a in appointments:
        by_status[a.status] = by_status.get(a.status, 0) + 1
        by_doctor[a.doctor.name if a.doctor else 'Unknown'] = \
            by_doctor.get(a.doctor.name if a.doctor else 'Unknown', 0) + 1
        by_treatment[a.treatment.name if a.treatment else 'Unknown'] = \
            by_treatment.get(a.treatment.name if a.treatment else 'Unknown', 0) + 1
    return {
        'from': request.args.get('from'),
        'to': request.args.get('to'),
        'total': len(appointments),
        'by_status': by_status,
        'by_doctor': by_doctor,
        'by_treatment': by_treatment,
    }


def _csv_response(filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


@reports_bp.route('/api/reports/revenue', methods=['GET'])
@require_admin
def revenue_report():
    return jsonify(revenue_data())


@reports_bp.route('/api/reports/revenue.csv', methods=['GET'])
@require_admin
def revenue_csv():
    data = revenue_data()
    rows = [[d['date'], d['billed'], d['collected']] for d in data['by_day']]
    rows.append(['TOTAL', data['total_billed'], data['total_collected']])
    return _csv_response('revenue.csv', ['Date', 'Billed', 'Collected'], rows)


@reports_bp.route('/api/reports/appointments', methods=['GET'])
@require_admin
def appointments_report():
    return jsonify(appointments_data())


@reports_bp.route('/api/reports/appointments.csv', methods=['GET'])
@require_admin
def appointments_csv():
    data = appointments_data()
    rows = [[k, v] for k, v in sorted(data['by_doctor'].items())]
    return _csv_response('appointments_by_doctor.csv', ['Doctor', 'Appointments'], rows)


@reports_bp.route('/api/reports/summary', methods=['GET'])
@require_admin
def summary():
    expenses = round(sum(e.amount for e in Expense.query.all()), 2)
    rev = revenue_data()
    return jsonify({
        'patients': Patient.query.count(),
        'revenue': rev,
        'appointments': appointments_data(),
        'expenses_total': expenses,
        'profit': round(rev['total_collected'] - expenses, 2),
    })
