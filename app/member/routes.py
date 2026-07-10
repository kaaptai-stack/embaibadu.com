import re
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.extensions import db, limiter
from app.models import (
    Profile, EmbaDetails, WorkHistory, Company, Industry, Payment, Referral, Announcement,
    ROLE_MEMBER, STATUS_ACTIVE, PAYMENT_SUCCESS,
)
from app.utils import (
    is_strong_password, normalize_company_name, allowed_image, save_upload, send_dev_email,
)
from flask import current_app

member_bp = Blueprint("member", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def ensure_profile(user):
    if not user.profile:
        profile = Profile(user_id=user.id)
        db.session.add(profile)
        db.session.commit()
    if not user.emba_details:
        details = EmbaDetails(user_id=user.id)
        db.session.add(details)
        db.session.commit()


@member_bp.route("/dashboard")
@login_required
def dashboard():
    ensure_profile(current_user)
    announcements = Announcement.query.filter_by(active=True).order_by(Announcement.created_at.desc()).limit(5).all()
    has_access = current_user.current_access_valid()
    valid_until = current_user.access_valid_until()
    return render_template(
        "member/dashboard.html",
        announcements=announcements,
        has_access=has_access,
        valid_until=valid_until,
        companies=Company.query.order_by(Company.name).all(),
        industries=Industry.query.order_by(Industry.name).all(),
    )


@member_bp.route("/profile/save", methods=["POST"])
@login_required
def profile_save():
    ensure_profile(current_user)
    user = current_user
    profile = user.profile

    name = request.form.get("name", "").strip()
    if not name:
        return jsonify(ok=False, error="Full name is required."), 400
    user.name = name

    profile.mobile_personal = request.form.get("mobile_personal", "").strip() or None
    profile.mobile_personal_whatsapp = bool(request.form.get("mobile_personal_whatsapp"))
    profile.mobile_personal_hide = bool(request.form.get("mobile_personal_hide"))

    profile.mobile_office = request.form.get("mobile_office", "").strip() or None
    profile.mobile_office_whatsapp = bool(request.form.get("mobile_office_whatsapp"))
    profile.mobile_office_hide = bool(request.form.get("mobile_office_hide"))

    profile.facebook_url = request.form.get("facebook_url", "").strip() or None
    profile.linkedin_url = request.form.get("linkedin_url", "").strip() or None
    profile.current_designation = request.form.get("current_designation", "").strip() or None
    profile.blood_group = request.form.get("blood_group") or None
    profile.location = request.form.get("location", "").strip() or None

    career_start_year = request.form.get("career_start_year", "").strip()
    profile.career_start_year = int(career_start_year) if career_start_year.isdigit() else None

    company_choice = request.form.get("current_company")
    new_company_name = request.form.get("new_company_name", "").strip()
    if company_choice == "__new__" and new_company_name:
        profile.current_company_id = _get_or_create_company(new_company_name, user.id)
    elif company_choice and company_choice.isdigit():
        profile.current_company_id = int(company_choice)

    industry_names = [n.strip() for n in request.form.get("industries", "").split(",") if n.strip()]
    profile.industries = []
    for iname in industry_names:
        industry = Industry.query.filter(db.func.lower(Industry.name) == iname.lower()).first()
        if not industry:
            industry = Industry(name=iname)
            db.session.add(industry)
            db.session.flush()
        profile.industries.append(industry)

    WorkHistory.query.filter_by(user_id=user.id).delete()
    prev_ids = request.form.getlist("prev_company_id[]")
    prev_new_names = request.form.getlist("prev_company_new[]")
    for idx, (cid, new_name) in enumerate(zip(prev_ids, prev_new_names)):
        company_id = None
        if cid == "__new__" and new_name.strip():
            company_id = _get_or_create_company(new_name, user.id)
        elif cid and cid.isdigit():
            company_id = int(cid)
        if company_id:
            db.session.add(WorkHistory(user_id=user.id, company_id=company_id, sort_order=idx))

    db.session.commit()
    return jsonify(ok=True, message="Profile saved.")


def _get_or_create_company(raw_name, created_by_user_id):
    norm = normalize_company_name(raw_name)
    company = Company.query.filter(db.func.lower(Company.name) == norm.lower()).first()
    if not company:
        company = Company(name=norm, flagged_for_review=True, created_by_user_id=created_by_user_id)
        db.session.add(company)
        db.session.flush()
    return company.id


@member_bp.route("/profile/photo", methods=["POST"])
@login_required
def upload_photo():
    ensure_profile(current_user)
    file = request.files.get("photo")
    if not file or not file.filename:
        flash("Please choose an image file.", "error")
        return redirect(url_for("member.dashboard"))
    if not allowed_image(file.filename, current_app.config["ALLOWED_IMAGE_EXTENSIONS"]):
        flash("Only JPG/PNG images are allowed.", "error")
        return redirect(url_for("member.dashboard"))
    filename = save_upload(file, "photos")
    current_user.profile.photo_filename = filename
    db.session.commit()
    flash("Profile photo updated.", "success")
    return redirect(url_for("member.dashboard"))


@member_bp.route("/profile/banner", methods=["POST"])
@login_required
def upload_banner():
    ensure_profile(current_user)
    file = request.files.get("banner")
    if not file or not file.filename:
        flash("Please choose an image file.", "error")
        return redirect(url_for("member.dashboard"))
    if not allowed_image(file.filename, current_app.config["ALLOWED_IMAGE_EXTENSIONS"]):
        flash("Only JPG/PNG images are allowed.", "error")
        return redirect(url_for("member.dashboard"))
    filename = save_upload(file, "banners")
    current_user.profile.banner_filename = filename
    db.session.commit()
    flash("Banner photo updated.", "success")
    return redirect(url_for("member.dashboard"))


@member_bp.route("/profile/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")

        if not current_user.check_password(current_pw):
            flash("Current password is incorrect.", "error")
        elif new_pw != confirm_pw:
            flash("New passwords do not match.", "error")
        elif not is_strong_password(new_pw):
            flash("Password must be at least 8 characters and include a letter, a number, and a special character.", "error")
        else:
            current_user.set_password(new_pw)
            db.session.commit()
            flash("Password changed successfully.", "success")
            return redirect(url_for("member.dashboard"))

    return render_template("member/change_password.html")


@member_bp.route("/payments/mine")
@login_required
def payments_mine():
    payments = Payment.query.filter_by(user_id=current_user.id).order_by(Payment.created_at.desc()).all()
    return render_template("member/payments_mine.html", payments=payments)


@member_bp.route("/refer", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per hour")
def refer():
    if request.method == "POST":
        action = request.form.get("action", "send")

        if action == "generate":
            referral = Referral(referrer_id=current_user.id)
            db.session.add(referral)
            db.session.commit()
            flash("Referral link generated below.", "success")
            return redirect(url_for("member.refer"))

        raw = request.form.get("emails", "")
        candidates = [e.strip().lower() for e in re.split(r"[,\n;\s]+", raw) if e.strip()]
        emails = sorted(set(e for e in candidates if EMAIL_RE.match(e)))

        if not emails:
            flash("Enter at least one valid email address.", "error")
            return redirect(url_for("member.refer"))

        for invitee_email in emails:
            referral = Referral(referrer_id=current_user.id, invitee_email=invitee_email)
            db.session.add(referral)
            db.session.commit()

            referral_url = url_for("auth.register", ref=referral.token, _external=True)
            send_dev_email(
                to_email=invitee_email,
                subject=f"{current_user.name} invited you to join the EMBA Member Directory",
                body_html=f"{current_user.name} has invited you to join the IBA EMBA Member Association directory. This link expires in 7 days.",
                link_url=referral_url,
            )

        flash(f"Sent a unique referral link to {len(emails)} email address(es) — see Dev Inbox.", "success")
        return redirect(url_for("member.refer"))

    my_referrals = Referral.query.filter_by(referrer_id=current_user.id).order_by(Referral.id.desc()).all()
    return render_template("member/refer.html", referrals=my_referrals)
