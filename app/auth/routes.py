from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db, limiter
from app.models import (
    User, Referral, MemberActivity,
    STATUS_PENDING, STATUS_ACTIVE, STATUS_UNREGISTERED, ROLE_MEMBER, REFERRAL_USED,
)
from app.utils import (
    is_strong_password,
    send_dev_email,
    make_timed_token,
    read_timed_token,
)

auth_bp = Blueprint("auth", __name__)

VERIFY_SALT = "verify-email"
RESET_SALT = "reset-password"


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def register():
    token = request.args.get("ref") or request.form.get("ref")
    referral = Referral.query.filter_by(token=token).first() if token else None

    if not referral or not referral.is_valid():
        return render_template("auth/register_invalid.html")

    # a targeted invite may match a preloaded (not-yet-registered) roster row —
    # prefill the name so the applicant can confirm rather than retype it
    preloaded = None
    if referral.invitee_email:
        preloaded = User.query.filter_by(email=referral.invitee_email, status=STATUS_UNREGISTERED).first()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        existing = User.query.filter_by(email=email).first()
        claiming_preload = existing is not None and existing.status == STATUS_UNREGISTERED

        error = None
        if not name:
            error = "Full name is required."
        elif not email:
            error = "Email is required."
        elif existing and not claiming_preload:
            error = "An account with this email already exists."
        elif password != confirm:
            error = "Passwords do not match."
        elif not is_strong_password(password):
            error = "Password must be at least 8 characters and include a letter, a number, and a special character."

        if error:
            flash(error, "error")
            return render_template("auth/register.html", referral=referral, name=name, email=email, preloaded=preloaded)

        if claiming_preload:
            # reuse the preloaded roster row (and its already-known profile info)
            # instead of creating a duplicate account
            user = existing
            user.name = name
            user.status = STATUS_PENDING
            user.referred_by_user_id = referral.referrer_id
        else:
            user = User(name=name, email=email, role=ROLE_MEMBER, status=STATUS_PENDING,
                        referred_by_user_id=referral.referrer_id)
            db.session.add(user)

        user.set_password(password)
        db.session.flush()

        referral.status = REFERRAL_USED
        referral.used_at = datetime.utcnow()
        referral.registered_user_id = user.id
        db.session.commit()

        verify_token = make_timed_token({"user_id": user.id}, VERIFY_SALT)
        verify_url = url_for("auth.verify_email", token=verify_token, _external=True)
        send_dev_email(
            to_email=user.email,
            subject="Verify your EMBA Member account email",
            body_html=f"Hi {user.name}, click to verify your email address.",
            link_url=verify_url,
        )
        flash("Account created. Check the Dev Inbox for your verification email link.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", referral=referral, name=preloaded.name if preloaded else "",
                           email=referral.invitee_email or "", preloaded=preloaded)


@auth_bp.route("/verify-email/<token>")
def verify_email(token):
    data = read_timed_token(token, VERIFY_SALT, max_age=60 * 60 * 24)
    if not data:
        flash("This verification link is invalid or has expired.", "error")
        return redirect(url_for("auth.login"))

    user = db.session.get(User, data["user_id"])
    if not user:
        flash("Account not found.", "error")
        return redirect(url_for("auth.login"))

    if not user.email_verified_at:
        user.email_verified_at = datetime.utcnow()
        db.session.commit()

    flash("Email verified. Your registration is now pending admin approval.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("15 per hour")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("member.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html", email=email)

        if user.status == STATUS_UNREGISTERED:
            flash("This member record hasn't been registered yet. Ask an existing member for a referral link.", "error")
            return render_template("auth/login.html", email=email)

        if not user.email_verified_at:
            flash("Please verify your email first. Check the Dev Inbox for the verification link.", "error")
            return render_template("auth/login.html", email=email)

        if user.status == STATUS_PENDING:
            flash("Your registration is awaiting admin approval.", "error")
            return render_template("auth/login.html", email=email)

        if user.status != STATUS_ACTIVE:
            flash("Your account is not active. Please contact an administrator.", "error")
            return render_template("auth/login.html", email=email)

        login_user(user, remember=remember, duration=None)
        user.last_active_at = datetime.utcnow()
        db.session.add(MemberActivity(user_id=user.id, action="login"))
        db.session.commit()

        next_url = request.args.get("next")
        if user.role in ("admin", "super_admin"):
            return redirect(next_url or url_for("admin.dashboard"))
        return redirect(next_url or url_for("member.dashboard"))

    return render_template("auth/login.html", email="")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.landing"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            reset_token = make_timed_token({"user_id": user.id}, RESET_SALT)
            reset_url = url_for("auth.reset_password", token=reset_token, _external=True)
            send_dev_email(
                to_email=user.email,
                subject="Reset your EMBA Member password",
                body_html=f"Hi {user.name}, click the link to set a new password. This link expires in 60 minutes.",
                link_url=reset_url,
            )
        flash("If that email is registered, a password reset link has been sent (check the Dev Inbox).", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    data = read_timed_token(token, RESET_SALT, max_age=60 * 60)
    if not data:
        flash("This password reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password"))

    user = db.session.get(User, data["user_id"])
    if not user:
        flash("Account not found.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("auth/reset_password.html", token=token)
        if not is_strong_password(password):
            flash("Password must be at least 8 characters and include a letter, a number, and a special character.", "error")
            return render_template("auth/reset_password.html", token=token)

        user.set_password(password)
        db.session.commit()
        flash("Password updated. You can now log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)
