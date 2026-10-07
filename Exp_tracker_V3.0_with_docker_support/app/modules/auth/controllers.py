"""Auth routes (Controller layer) — login (with 2FA), roles, profile, user admin."""
import functools
import time

from flask import current_app, flash, g, jsonify, redirect, render_template, \
    request, session, url_for

from ... import limiter
from ...db import get_db, log_action
from . import bp, models

PUBLIC_ENDPOINTS = {"auth.login", "auth.login_totp", "healthz", "metrics", "static"}


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
        if endpoint.startswith(("api.", "api_v1.")):
            return jsonify(error="authentication required"), 401
        return redirect(url_for("auth.login"))
    db = get_db()
    g.is_admin = models.is_admin(db, session["user"])
    timeout = models.effective_timeout(
        db, session["user"],
        current_app.config.get("SESSION_TIMEOUT_MINUTES", 15))
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
@limiter.limit("10 per minute")
def login():
    if session.get("user"):
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = request.form.get("username", "")
        if models.verify(get_db(), username, request.form.get("password", "")):
            if models.totp_enabled(get_db(), username):
                # Second factor required — keep a pending marker only.
                session.clear()  # avoid session fixation
                session["pending_user"] = username
                session["last_active"] = time.time()
                return redirect(url_for("auth.login_totp"))
            session.clear()  # avoid session fixation
            session["user"] = username
            session["last_active"] = time.time()
            return redirect(url_for("dashboard.index"))
        flash("Invalid username or password.", "error")
    return render_template("auth/login.html")


@bp.route("/login/totp", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login_totp():
    username = session.get("pending_user")
    if not username:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        if models.totp_verify(get_db(), username, request.form.get("code", "")):
            session.clear()  # fresh session for the authenticated user
            session["user"] = username
            session["last_active"] = time.time()
            return redirect(url_for("dashboard.index"))
        flash("Invalid or expired code.", "error")
    return render_template("auth/totp.html", username=username)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    """User profile — timeout override and two-factor auth setup."""
    db = get_db()
    username = session.get("user", "")
    if request.method == "POST":
        err = models.set_timeout(db, username, request.form.get("timeout_minutes", ""))
        if err:
            flash(err, "error")
        else:
            flash("Session timeout updated.", "success")
        return redirect(url_for("auth.profile"))
    user = models.get_user(db, username)
    default_minutes = current_app.config.get("SESSION_TIMEOUT_MINUTES", 15)
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
def totp_enable():
    """Generate a pending TOTP secret and show it once for enrollment."""
    db = get_db()
    username = session.get("user", "")
    secret, err = models.totp_start(db, username)
    if err:
        flash(err, "error")
        return redirect(url_for("auth.profile"))
    session["totp_secret"] = secret  # shown once on the next profile render
    return redirect(url_for("auth.profile"))


@bp.route("/profile/totp/confirm", methods=["POST"])
def totp_confirm():
    db = get_db()
    err = models.totp_confirm(db, session.get("user", ""),
                              request.form.get("code", ""))
    if err:
        flash(err, "error")
    else:
        flash("Two-factor authentication enabled.", "success")
    return redirect(url_for("auth.profile"))


@bp.route("/profile/totp/disable", methods=["POST"])
def totp_disable():
    db = get_db()
    err = models.totp_disable(db, session.get("user", ""),
                              request.form.get("code", ""))
    if err:
        flash(err, "error")
    else:
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
        role = request.form.get("role", "admin")
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
        income=sums["income"], expense=sums["expense"], count=sums["count"],
        categories=models.managed_categories(db, user_id),
        recent=models.managed_recent(db, user_id, limit=10),
    )


@bp.route("/users/password/<int:user_id>", methods=["POST"])
@admin_required
def reset_password(user_id):
    db = get_db()
    log_action(db, session.get("user"), "reset_password", "users", user_id)
    err = models.set_password(db, user_id, request.form.get("password", ""))
    if err:
        flash(err, "error")
    else:
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
    db = get_db()
    rows = db.execute(
        """SELECT a.*, u.username AS actor FROM audit_log a
           LEFT JOIN users u ON u.id=a.user_id
           ORDER BY a.id DESC LIMIT 200""").fetchall()
    retention = current_app.config.get("AUDIT_RETENTION_DAYS") or 0
    return render_template("auth/audit.html", entries=rows, retention=retention)


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
    cur = db.execute("DELETE FROM audit_log WHERE timestamp < ?", (cutoff,))
    db.commit()
    flash(f"Purged {cur.rowcount} audit entries older than {days} day(s).", "success")
    return redirect(url_for("auth.audit"))
