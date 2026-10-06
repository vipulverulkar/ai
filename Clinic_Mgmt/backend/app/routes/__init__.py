"""Route registration (MVC: wires Controllers to the app)."""
from app.routes.appointments import appointments_bp
from app.routes.auditlog import audit_bp
from app.routes.auth import auth_bp
from app.routes.bills import bills_bp
from app.routes.doctors import doctors_bp
from app.routes.expenses import expenses_bp
from app.routes.lab import lab_bp
from app.routes.lookups import lookups_bp
from app.routes.maintenance import maintenance_bp
from app.routes.patients import patients_bp
from app.routes.prescriptions import prescriptions_bp
from app.routes.reports import reports_bp
from app.routes.search import search_bp
from app.routes.settings import settings_bp
from app.routes.system import system_bp
from app.routes.treatments import treatments_bp
from app.routes.users import users_bp


def register_blueprints(app):
    for bp in (appointments_bp, audit_bp, auth_bp, bills_bp, doctors_bp,
               expenses_bp, lab_bp, lookups_bp, maintenance_bp, patients_bp,
               prescriptions_bp, reports_bp, search_bp, settings_bp, system_bp,
               treatments_bp, users_bp):
        app.register_blueprint(bp)
