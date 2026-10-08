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
        data/         models.py · controllers.py · templates/  (CSV import + SQL/JSON/CSV backup/restore)
        api/          models.py · controllers.py   (JSON, no views)
"""
import json
import logging
import os
import time
from datetime import date, datetime, timedelta

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

from .config import Config
from .db import close_db, connect, get_db, init_db
from .helpers import format_inr

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("exptracker")

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])

# Optional Prometheus metrics (guarded import — app works without the lib).
try:
    from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
    REQUEST_COUNTER = Counter(
        "exptracker_http_requests_total", "HTTP requests",
        ["method", "endpoint", "status"])
except Exception:  # noqa: BLE001
    REQUEST_COUNTER = None


class JsonLogFormatter(logging.Formatter):
    """Minimal JSON-lines formatter for structured logs."""

    def format(self, record):
        return json.dumps({
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        })


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    if app.config["SECRET_KEY"] == "dev-only-change-me-in-production":
        log.warning("SECRET_KEY not set — using insecure dev default. Set SECRET_KEY env var.")

    # Keep deterministic test behaviour: no rate limiting under TESTING.
    if app.config.get("TESTING"):
        app.config["RATELIMIT_ENABLED"] = False

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)

    _init_sentry(app)
    _init_sessions(app)

    csrf.init_app(app)
    limiter.init_app(app)

    app.teardown_appcontext(close_db)
    _register_template_helpers(app)
    _register_hooks(app)
    _register_blueprints(app)

    # Ensure tables exist on startup (idempotent).
    init_db(app.config)

    # Optional startup maintenance: FX refresh, audit retention, auto-backup.
    from .fx import refresh_rates
    try:
        if refresh_rates(app.config):
            log.info("FX rates refreshed (%s currencies available).",
                     len(app.config["CURRENCY_CODES"]))
    except Exception as e:  # noqa: BLE001
        log.warning("FX refresh skipped: %s", e)
    _purge_audit(app)
    if app.config.get("AUTO_BACKUP"):
        try:
            from .jobs import run_backup
            path = run_backup(app.config)
            log.info("Automatic backup written to %s", path)
        except Exception as e:  # noqa: BLE001
            log.warning("Automatic backup failed: %s", e)

    from .modules.auth import models as auth_models
    conn = connect(app.config)
    try:
        if auth_models.using_default_credentials(conn):
            log.warning("Default login credentials in use (admin/admin) — "
                        "change the password in the users table.")
    finally:
        conn.close()
    return app


def _init_sentry(app):
    """Optional Sentry error tracking (enabled when SENTRY_DSN is set)."""
    dsn = app.config.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(dsn=dsn, integrations=[FlaskIntegration()],
                        traces_sample_rate=0.0)
        log.info("Sentry error tracking enabled.")
    except ImportError:
        log.warning("SENTRY_DSN set but sentry-sdk is not installed — skipping.")


def _init_sessions(app):
    """Server-side sessions via Flask-Session when available.

    Uses the ``cachelib`` backend (``FileSystemCache``) on Flask-Session
    >= 0.6; falls back to the legacy ``filesystem`` type on older versions.
    """
    if (app.config.get("SESSION_TYPE") or "cookie") == "cookie":
        return
    try:
        from flask_session import Session
    except ImportError:
        log.warning("flask-session not installed — falling back to cookie sessions.")
        return
    # Migrate legacy SESSION_TYPE=filesystem to the CacheLib backend to avoid
    # DeprecationWarnings (SESSION_FILE_DIR / FileSystemSessionInterface are
    # deprecated and will be removed in Flask-Session 1.0).
    if (app.config.get("SESSION_TYPE") or "").lower() == "filesystem":
        try:
            from cachelib.file import FileSystemCache
            cache_dir = app.config.get("SESSION_FILE_DIR")
            os.makedirs(cache_dir, exist_ok=True)
            app.config["SESSION_TYPE"] = "cachelib"
            app.config["SESSION_CACHELIB"] = FileSystemCache(cache_dir, threshold=500, mode=0o600)
        except ImportError:
            # cachelib not available (very old Flask-Session) — use legacy type.
            os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
    try:
        Session(app)
    except ValueError:
        # Old Flask-Session without SESSION_TYPE=cachelib support — retry legacy.
        app.config["SESSION_TYPE"] = "filesystem"
        app.config.pop("SESSION_CACHELIB", None)
        os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
        Session(app)


def _purge_audit(app):
    """Drop audit entries older than AUDIT_RETENTION_DAYS (0 = keep all)."""
    days = app.config.get("AUDIT_RETENTION_DAYS") or 0
    if days <= 0:
        return
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        conn = connect(app.config)
        try:
            conn.execute("DELETE FROM audit_logs WHERE timestamp < ?", (cutoff,))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        log.warning("Audit purge skipped: %s", e)


def _register_template_helpers(app):
    app.add_template_filter(lambda v: format_inr(v, 2), "money")
    app.add_template_filter(lambda v: format_inr(v, 0), "money0")

    @app.context_processor
    def inject_globals():
        from flask import g, session
        idle_minutes = g.get("idle_timeout_minutes")
        idle_remaining = None
        if idle_minutes and session.get("user"):
            last = session.get("last_active")
            if last is not None:
                idle_remaining = max(
                    0, int(round(idle_minutes * 60 - (time.time() - float(last)))))
        return {
            "currency": app.config["CURRENCY"],
            "app_version": app.config["APP_VERSION"],
            "current_year": date.today().year,
            "base_currency": app.config["BASE_CURRENCY"],
            "currency_codes": app.config["CURRENCY_CODES"],
            "is_admin": bool(g.get("is_admin", False)),
            "idle_timeout_minutes": idle_minutes,
            "idle_remaining_seconds": idle_remaining,
        }


def _register_hooks(app):
    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if REQUEST_COUNTER is not None:
            try:
                REQUEST_COUNTER.labels(request.method,
                                       request.endpoint or "unknown",
                                       resp.status_code).inc()
            except Exception:  # noqa: BLE001 — metrics must never break requests
                pass
        return resp

    @app.route("/healthz")
    @csrf.exempt
    def healthz():
        try:
            db = get_db()
            db.execute("SELECT 1").fetchone()
            return jsonify(status="ok", version=app.config["APP_VERSION"],
                           db=db.engine), 200
        except Exception:  # noqa: BLE001
            return jsonify(status="error"), 500

    if REQUEST_COUNTER is not None:
        @app.route("/metrics")
        @csrf.exempt
        def metrics():
            from flask import Response
            return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404,
                               message="The page you asked for doesn't exist."), 404

    @app.errorhandler(413)
    def too_large(e):
        flash("Upload too large.", "error")
        return redirect(request.referrer or url_for("transactions.index"))

    @app.errorhandler(500)
    def server_error(e):
        return render_template("error.html", code=500,
                               message="Something went wrong. Please try again."), 500


def _register_blueprints(app):
    from .modules.api import bp as api_bp, bp_v1 as api_v1_bp
    from .modules.auth import bp as auth_bp
    from .modules.budgets import bp as budgets_bp
    from .modules.categories import bp as categories_bp
    from .modules.dashboard import bp as dashboard_bp
    from .modules.data import bp as data_bp
    from .modules.recurring import bp as recurring_bp
    from .modules.reports import bp as reports_bp
    from .modules.transactions import bp as transactions_bp

    for bp in (auth_bp, dashboard_bp, transactions_bp, categories_bp,
               budgets_bp, reports_bp, data_bp, api_bp, api_v1_bp, recurring_bp):
        app.register_blueprint(bp)
