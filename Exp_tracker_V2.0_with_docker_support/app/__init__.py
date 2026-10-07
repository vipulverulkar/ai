"""Expense Tracker — Flask application factory.

Structure (per-module MVC under app/modules/):

    app/
      __init__.py     create_app() factory, template filters, error handlers
      config.py       env-driven configuration
      db.py           SQLite/PostgreSQL adapter + schema bootstrap
      helpers.py      formatting / date utilities
      templates/      shared views (base.html, error.html)
      static/         style.css, app.js
      modules/
        auth/         models.py · controllers.py · templates/  (login guard, profile, user admin)
        dashboard/    models.py · controllers.py · templates/
        transactions/ models.py · controllers.py · templates/
        categories/   models.py · controllers.py · templates/
        budgets/      models.py · controllers.py · templates/
        reports/      models.py · controllers.py · templates/
        data/         models.py · controllers.py · templates/  (CSV import + JSON backup/restore)
        api/          models.py · controllers.py   (JSON, no views)
"""
import logging
from datetime import date

from flask import Flask, flash, jsonify, redirect, render_template, url_for

from .config import Config
from .db import close_db, connect, get_db, init_db
from .helpers import format_inr

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("exptracker")


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    if app.config["SECRET_KEY"] == "dev-only-change-me-in-production":
        log.warning("SECRET_KEY not set — using insecure dev default. Set SECRET_KEY env var.")

    app.teardown_appcontext(close_db)
    _register_template_helpers(app)
    _register_hooks(app)
    _register_blueprints(app)

    # Ensure tables exist on startup (idempotent).
    init_db(app.config)
    from .modules.auth import models as auth_models
    conn = connect(app.config)
    try:
        if auth_models.using_default_credentials(conn):
            log.warning("Default login credentials in use (admin/admin) — "
                        "change the password in the users table.")
    finally:
        conn.close()
    return app


def _register_template_helpers(app):
    app.add_template_filter(lambda v: format_inr(v, 2), "money")
    app.add_template_filter(lambda v: format_inr(v, 0), "money0")

    @app.context_processor
    def inject_globals():
        return {
            "currency": app.config["CURRENCY"],
            "app_version": app.config["APP_VERSION"],
            "current_year": date.today().year,
        }


def _register_hooks(app):
    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return resp

    @app.route("/healthz")
    def healthz():
        try:
            db = get_db()
            db.execute("SELECT 1").fetchone()
            return jsonify(status="ok", version=app.config["APP_VERSION"],
                           db=db.engine), 200
        except Exception:  # noqa: BLE001
            return jsonify(status="error"), 500

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404,
                               message="The page you asked for doesn't exist."), 404

    @app.errorhandler(413)
    def too_large(e):
        flash("Upload too large (max 2 MB).", "error")
        return redirect(url_for("transactions.index"))

    @app.errorhandler(500)
    def server_error(e):
        return render_template("error.html", code=500,
                               message="Something went wrong. Please try again."), 500


def _register_blueprints(app):
    from .modules.api import bp as api_bp
    from .modules.auth import bp as auth_bp
    from .modules.budgets import bp as budgets_bp
    from .modules.categories import bp as categories_bp
    from .modules.dashboard import bp as dashboard_bp
    from .modules.data import bp as data_bp
    from .modules.reports import bp as reports_bp
    from .modules.transactions import bp as transactions_bp

    for bp in (auth_bp, dashboard_bp, transactions_bp, categories_bp,
                budgets_bp, reports_bp, data_bp, api_bp):
        app.register_blueprint(bp)
