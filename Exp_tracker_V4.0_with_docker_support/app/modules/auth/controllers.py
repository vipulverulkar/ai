"""Auth routes (Controller layer) — login (with 2FA), roles, profile, user admin."""
import functools
import time

from flask import current_app, flash, g, jsonify, redirect, render_template, \
    request, session, url_for

from ... import limiter
from ...config import SESSION_TIMEOUT_MINUTES as _DEFAULT_TIMEOUT
from ...config import TOTP_PENDING_TTL_SECONDS as PENDING_TTL
from ...db import get_db, log_action
from ...helpers import page_window, paginate
from . import bp, models

PUBLIC_ENDPOINTS = {"auth.login", "auth.login_totp", "healthz", "manifest", "static"}


def _pending_ttl():
    """2FA half-session lifetime in seconds (runtime config, env default)."""
    try:
        return int(current_app.config.get("TOTP_PENDING_TTL_SECONDS", PENDING_TTL)
                   or PENDING_TTL)
    except (RuntimeError, ValueError, TypeError):
        return PENDING_TTL


def _default_timeout():
    """Site-wide idle-timeout minutes (runtime config, env default)."""
    try:
        return int(current_app.config.get("SESSION_TIMEOUT_MINUTES", _DEFAULT_TIMEOUT)
                   or _DEFAULT_TIMEOUT)
    except (RuntimeError, ValueError, TypeError):
        return _DEFAULT_TIMEOUT


def _rotate_session():
    """Clear the session and rotate its id (anti-fixation).

    session.clear() alone keeps the same session id; Flask-Session can
    regenerate it server-side. Falls back to clear-only when the
    interface has no regenerate (e.g. plain cookie sessions).
    """
    session.clear()
    try:
        regenerate = getattr(current_app.session_interface, "regenerate", None)
        if regenerate is not None:
            regenerate(session)
    except Exception:  # noqa: BLE001 — rotation is best-effort
        pass


def _audit(actor, action, target_table=None, target_id=None, details=None):
    """Best-effort audit write — auth events must never break the flow."""
    try:
        log_action(get_db(), actor, action, target_table, target_id, details)
    except Exception:  # noqa: BLE001
        pass


@bp.before_app_request
def require_login():
    """Gate every route behind the session; healthz/static stay public.

    Also enforces the idle timeout and resolves the current user's role
    (g.is_admin drives both route guards and template visibility).
    """
    if not session.get("user"):
        endpoint = request.endpoint or ""
        if endpoint in PUBLIC_ENDPOINTS:
            return None
        if endpoint.startswith(("api.", "api_v1.")) or endpoint == "auth.ping":
            return jsonify(error="authentication required"), 401
        return redirect(url_for("auth.login"))
    db = get_db()
    g.is_admin = models.is_admin(db, session["user"])
    timeout = models.effective_timeout(
        db, session["user"], _default_timeout())
    g.idle_timeout_minutes = timeout  # shown as a live countdown in the nav
    now = time.time()
    last = session.get("last_active")
    if last is not None and now - float(last) > timeout * 60:
        session.clear()
        flash("Signed out due to inactivity. Please sign in again.", "error")
        return redirect(url_for("auth.login"))
    session["last_active"] = now
    return None


def admin_required(view):
    """Route guard: only users with the admin role may proceed."""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        if not g.get("is_admin", False):
            flash("That action requires an admin account.", "error")
            return redirect(url_for("dashboard.index"))
        return view(*args, **kwargs)
    return wrapper


@bp.route("/login", methods=["GET", "POST"])
# NOTE: limits are per gunicorn worker (default 2 x memory://),
# so the effective per-IP budget is ~2x the value below.
@limiter.limit("5 per minute")
def login():
    if session.get("user"):
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = request.form.get("username", "")
        if models.verify(get_db(), username, request.form.get("password", "")):
            if models.totp_enabled(get_db(), username):
                # Second factor required — keep a pending marker only.
                _rotate_session()
                session["pending_user"] = username
                session["pending_at"] = time.time()
                session["last_active"] = time.time()
                return redirect(url_for("auth.login_totp"))
            _rotate_session()
            session["user"] = username
            session["last_active"] = time.time()
            _audit(username, "login", details="password login")
            return redirect(url_for("dashboard.index"))
        _audit(username or None, "login_failed", details="invalid credentials")
        flash("Invalid username or password.", "error")
    return render_template("auth/login.html")


@bp.route("/login/totp", methods=["GET", "POST"])
# NOTE: limits are per gunicorn worker (default 2 x memory://),
# so the effective per-IP budget is ~2x the value below.
@limiter.limit("5 per minute")
def login_totp():
    username = session.get("pending_user")
    if not username:
        return redirect(url_for("auth.login"))
    # The password-validated half-session expires quickly so the second
    # factor cannot be brute-forced indefinitely.
    ttl = _pending_ttl()
    try:
        pending_age = time.time() - float(session.get("pending_at", 0))
    except (ValueError, TypeError):
        pending_age = ttl + 1
    if pending_age > ttl:
        session.clear()
        flash("Verification expired. Please sign in again.", "error")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        if models.totp_verify(get_db(), username, request.form.get("code", "")):
            _rotate_session()
            session["user"] = username
            session["last_active"] = time.time()
            _audit(username, "login", details="totp login")
            return redirect(url_for("dashboard.index"))
        _audit(username, "login_failed", details="bad totp code")
        flash("Invalid or expired code.", "error")
    return render_template("auth/totp.html", username=username)


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    user = session.get("user")
    _rotate_session()
    if user:
        _audit(user, "logout")
    return redirect(url_for("auth.login"))


@bp.route("/session/ping")
def ping():
    """Heartbeat for the nav idle-timer: refreshes last_active on activity.

    require_login already stamped last_active for this request, so this just
    reports the fresh budget. Anonymous callers get 401 JSON (see the guard).
    """
    if not session.get("user"):
        return jsonify(error="authentication required"), 401
    timeout = (g.get("idle_timeout_minutes") or _default_timeout())
    remaining = int(round(timeout * 60))
    return jsonify(remaining=remaining, total=timeout * 60)


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    """User profile — timeout override (admins) and two-factor auth setup."""
    db = get_db()
    username = session.get("user", "")
    if request.method == "POST":
        if not g.get("is_admin", False):
            flash("Only admins can change the session timeout.", "error")
            return redirect(url_for("auth.profile"))
        err = models.set_timeout(db, username, request.form.get("timeout_minutes", ""))
        if err:
            flash(err, "error")
        else:
            flash("Session timeout updated.", "success")
        return redirect(url_for("auth.profile"))
    user = models.get_user(db, username)
    default_minutes = _default_timeout()
    pending_secret = session.pop("totp_secret", None)
    return render_template(
        "auth/profile.html", user=user,
        default_minutes=default_minutes,
        effective_minutes=models.effective_timeout(db, username, default_minutes),
        stats=models.managed_stats(db, user["id"]) if user else None,
        recent=models.managed_recent(db, user["id"]) if user else [],
        role=models.role_of(db, username),
        totp_available=models.totp_available(),
        totp_on=models.totp_enabled(db, username),
        totp_secret=pending_secret,
        totp_uri=(f"otpauth://totp/ExpenseTracker:{username}"
                  f"?secret={pending_secret}&issuer=ExpenseTracker"
                  if pending_secret else None),
    )


@bp.route("/profile/totp/enable", methods=["POST"])
# NOTE: limits are per gunicorn worker (default 2 x memory://),
# so the effective per-IP budget is ~2x the value below.
@limiter.limit("5 per minute")
def totp_enable():
    """Generate a pending TOTP secret and show it once for enrollment.

    Re-enrollment keeps the current secret active until the new one is
    confirmed — the account is never left without 2FA mid-flow.
    """
    db = get_db()
    username = session.get("user", "")
    if models.totp_enabled(db, username):
        try:
            import pyotp as _pyotp
        except ImportError:
            _pyotp = None
        if _pyotp is None:
            flash("2FA requires the pyotp package (pip install pyotp).", "error")
            return redirect(url_for("auth.profile"))
        secret = _pyotp.random_base32()
        session["totp_pending_secret"] = secret
        session["totp_secret"] = secret  # shown once on the next profile render
        _audit(username, "totp_reenroll_started")
        return redirect(url_for("auth.profile"))
    secret, err = models.totp_start(db, username)
    if err:
        flash(err, "error")
        return redirect(url_for("auth.profile"))
    session["totp_secret"] = secret  # shown once on the next profile render
    _audit(username, "totp_enroll_started")
    return redirect(url_for("auth.profile"))


@bp.route("/profile/totp/confirm", methods=["POST"])
# NOTE: limits are per gunicorn worker (default 2 x memory://),
# so the effective per-IP budget is ~2x the value below.
@limiter.limit("5 per minute")
def totp_confirm():
    db = get_db()
    pending = session.get("totp_pending_secret")
    if pending:
        err = models.totp_confirm_pending(db, session.get("user", ""),
                                          pending, request.form.get("code", ""))
        if err:
            _audit(session.get("user", ""), "totp_enable_failed")
            flash(err, "error")
        else:
            session.pop("totp_pending_secret", None)
            _audit(session.get("user", ""), "totp_enabled")
            flash("Two-factor authentication enabled.", "success")
        return redirect(url_for("auth.profile"))
    err = models.totp_confirm(db, session.get("user", ""),
                              request.form.get("code", ""))
    if err:
        _audit(session.get("user", ""), "totp_enable_failed")
        flash(err, "error")
    else:
        _audit(session.get("user", ""), "totp_enabled")
        flash("Two-factor authentication enabled.", "success")
    return redirect(url_for("auth.profile"))


@bp.route("/profile/totp/disable", methods=["POST"])
# NOTE: limits are per gunicorn worker (default 2 x memory://),
# so the effective per-IP budget is ~2x the value below.
@limiter.limit("5 per minute")
def totp_disable():
    db = get_db()
    err = models.totp_disable(db, session.get("user", ""),
                              request.form.get("code", ""))
    if err:
        _audit(session.get("user", ""), "totp_disable_failed")
        flash(err, "error")
    else:
        _audit(session.get("user", ""), "totp_disabled")
        flash("Two-factor authentication disabled.", "success")
    return redirect(url_for("auth.profile"))


# ---------- user management (admin only) ----------

@bp.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    """User management — list accounts, add new ones (with role)."""
    db = get_db()
    if request.method == "POST":
        username = request.form.get("username", "")
        role = request.form.get("role", "viewer")
        err = models.create_user(db, username, request.form.get("password", ""), role)
        if err:
            flash(err, "error")
        else:
            flash(f"User '{username.strip()}' added as {role}.", "success")
        return redirect(url_for("auth.users"))
    return render_template("auth/users.html", users=models.all_users(db),
                           roles=models.ROLES,
                           current=session.get("user", ""))


@bp.route("/users/<int:user_id>")
@admin_required
def user_profile(user_id):
    """Expense profile — the expenses managed for one user."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        flash("User not found.", "error")
        return redirect(url_for("dashboard.index"))
    sums = models.managed_stats(db, user_id)
    return render_template(
        "auth/user_profile.html", profile_user=row,
        income=sums["income"], expense=sums["expense"], saved=sums["saved"],
        count=sums["count"],
        categories=models.managed_categories(db, user_id),
        recent=models.managed_recent(db, user_id, limit=10),
    )


@bp.route("/users/password/<int:user_id>", methods=["POST"])
@admin_required
def reset_password(user_id):
    db = get_db()
    err = models.set_password(db, user_id, request.form.get("password", ""))
    if err:
        flash(err, "error")
    else:
        log_action(db, session.get("user"), "reset_password", "users", user_id)
        flash("Password updated.", "success")
    return redirect(url_for("auth.users"))


@bp.route("/users/role/<int:user_id>", methods=["POST"])
@admin_required
def change_role(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        flash("User not found.", "error")
    elif row["username"] == session.get("user"):
        flash("You cannot change your own role.", "error")
    else:
        err = models.set_role(db, user_id, request.form.get("role", ""))
        if err:
            flash(err, "error")
        else:
            flash(f"Role updated for '{row['username']}'.", "success")
            log_action(db, session.get("user"), "change_role", "users",
                       user_id, request.form.get("role", ""))
    return redirect(url_for("auth.users"))


@bp.route("/users/delete/<int:user_id>", methods=["POST"])
@admin_required
def delete_user(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        flash("User not found.", "error")
    elif row["username"] == session.get("user"):
        flash("You cannot delete your own account.", "error")
    elif models.count_users(db) <= 1:
        flash("Cannot delete the last remaining user.", "error")
    else:
        err = models.delete_user(db, user_id)
        if err:
            flash(err, "error")
        else:
            log_action(db, session.get("user"), "delete_user", "users", user_id,
                       f"Deleted user {row['username']}")
            flash(f"User '{row['username']}' deleted.", "success")
    return redirect(url_for("auth.users"))


# ---------- audit log (admin only) ----------

@bp.route("/audit")
@admin_required
def audit():
    from ...helpers import canonical_clean_args
    cleaned = canonical_clean_args(request.args, {"page": "1", "per_page": "25"})
    if cleaned is not None:
        return redirect(url_for("auth.audit", **cleaned))
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    page, per_page, total_pages, offset = paginate(
        total, request.args.get("page"), request.args.get("per_page"))
    rows = db.execute(
        """SELECT a.*, u.username AS actor FROM audit_logs a
           LEFT JOIN users u ON u.id=a.user_id
           ORDER BY a.id DESC LIMIT ? OFFSET ?""",
        (per_page, offset)).fetchall()
    retention = current_app.config.get("AUDIT_RETENTION_DAYS") or 0
    return render_template("auth/audit.html", entries=rows, retention=retention,
                           page=page, per_page=per_page, total=total,
                           total_pages=total_pages,
                           start=offset + 1 if total else 0,
                           end=min(offset + per_page, total),
                           pages=page_window(page, total_pages))


@bp.route("/audit/purge", methods=["POST"])
@admin_required
def audit_purge():
    """Delete audit entries older than AUDIT_RETENTION_DAYS (default 90)."""
    import datetime
    db = get_db()
    try:
        days = int(request.form.get("days", "") or 90)
    except ValueError:
        days = 90
    days = max(1, days)
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)) \
        .strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute("DELETE FROM audit_logs WHERE timestamp < ?", (cutoff,))
    db.commit()
    flash(f"Purged {cur.rowcount} audit entries older than {days} day(s).", "success")
    return redirect(url_for("auth.audit"))
