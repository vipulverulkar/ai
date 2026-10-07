"""Auth routes (Controller layer) — login, logout, profile and the login guard."""
import time

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for

from ...db import get_db
from . import bp, models

PUBLIC_ENDPOINTS = {"auth.login", "healthz", "static"}


@bp.before_app_request
def require_login():
    """Gate every route behind the session; healthz/static stay public.

    Also enforces the idle timeout: sessions idle longer than the effective
    timeout (per-user override or SESSION_TIMEOUT_MINUTES) are signed out.
    """
    if not session.get("user"):
        endpoint = request.endpoint or ""
        if endpoint in PUBLIC_ENDPOINTS:
            return None
        if endpoint.startswith("api."):
            return jsonify(error="authentication required"), 401
        return redirect(url_for("auth.login"))
    timeout = models.effective_timeout(
        get_db(), session["user"],
        current_app.config.get("SESSION_TIMEOUT_MINUTES", 15))
    now = time.time()
    last = session.get("last_active")
    if last is not None and now - float(last) > timeout * 60:
        session.clear()
        flash("Signed out due to inactivity. Please sign in again.", "error")
        return redirect(url_for("auth.login"))
    session["last_active"] = now
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = request.form.get("username", "")
        if models.verify(get_db(), username, request.form.get("password", "")):
            session.clear()  # avoid session fixation
            session["user"] = username
            session["last_active"] = time.time()
            return redirect(url_for("dashboard.index"))
        flash("Invalid username or password.", "error")
    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    """User profile — view account info and set a personal idle-timeout override."""
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
    stats = models.managed_stats(db, user["id"]) if user else None
    return render_template(
        "auth/profile.html", user=user,
        default_minutes=default_minutes,
        effective_minutes=models.effective_timeout(db, username, default_minutes),
        stats=stats,
        recent=models.managed_recent(db, user["id"]) if user else [],
    )


@bp.route("/users", methods=["GET", "POST"])
def users():
    """User management — list accounts and add new ones."""
    db = get_db()
    if request.method == "POST":
        username = request.form.get("username", "")
        err = models.create_user(db, username, request.form.get("password", ""))
        if err:
            flash(err, "error")
        else:
            flash(f"User '{username.strip()}' added.", "success")
        return redirect(url_for("auth.users"))
    return render_template("auth/users.html", users=models.all_users(db),
                           current=session.get("user", ""))


@bp.route("/users/<int:user_id>")
def user_profile(user_id):
    """Expense profile — the expenses managed for one user."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        flash("User not found.", "error")
        return redirect(url_for("auth.users"))
    sums = models.managed_stats(db, user_id)
    return render_template(
        "auth/user_profile.html", profile_user=row,
        income=sums["income"], expense=sums["expense"], count=sums["count"],
        categories=models.managed_categories(db, user_id),
        recent=models.managed_recent(db, user_id, limit=10),
    )


@bp.route("/users/password/<int:user_id>", methods=["POST"])
def reset_password(user_id):
    err = models.set_password(get_db(), user_id, request.form.get("password", ""))
    if err:
        flash(err, "error")
    else:
        flash("Password updated.", "success")
    return redirect(url_for("auth.users"))


@bp.route("/users/delete/<int:user_id>", methods=["POST"])
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
        models.delete_user(db, user_id)
        flash(f"User '{row['username']}' deleted.", "success")
    return redirect(url_for("auth.users"))
