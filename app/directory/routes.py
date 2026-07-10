from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify, abort, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, or_, desc, asc
from sqlalchemy.orm import aliased

from app.extensions import db, limiter
from app.models import (
    User, Profile, EmbaDetails, Batch, Company, Industry, WorkHistory, Payment,
    MemberActivity, profile_industries, STATUS_ACTIVE, PAYMENT_SUCCESS,
)
from app.utils import requires_paid_access, wa_link, visible_mobile_numbers

directory_bp = Blueprint("directory", __name__)

PrevCompany = aliased(Company)


def _accessible_members_query():
    """Active members with a currently valid (paid) access window.

    Joins every table filters/sort might need exactly once, up front, so
    _apply_filters/_apply_sort never have to join (and risk double-joining
    the same table when multiple filters combine).
    """
    today = datetime.utcnow().date()
    valid_payment = (
        db.session.query(Payment.user_id, func.max(Payment.valid_until).label("valid_until"))
        .filter(Payment.status == PAYMENT_SUCCESS)
        .group_by(Payment.user_id)
        .subquery()
    )
    q = (
        db.session.query(User)
        .join(valid_payment, valid_payment.c.user_id == User.id)
        .outerjoin(Profile, Profile.user_id == User.id)
        .outerjoin(Company, Profile.current_company_id == Company.id)
        .outerjoin(EmbaDetails, EmbaDetails.user_id == User.id)
        .outerjoin(Batch, EmbaDetails.batch_id == Batch.id)
        .outerjoin(WorkHistory, WorkHistory.user_id == User.id)
        .outerjoin(PrevCompany, WorkHistory.company_id == PrevCompany.id)
        .outerjoin(profile_industries, profile_industries.c.user_id == User.id)
        .outerjoin(Industry, profile_industries.c.industry_id == Industry.id)
        .filter(User.status == STATUS_ACTIVE, valid_payment.c.valid_until >= today)
        .distinct()
    )
    return q


def _apply_filters(q, args):
    search = args.get("q", "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                User.name.ilike(like),
                Company.name.ilike(like),
                Profile.current_designation.ilike(like),
                PrevCompany.name.ilike(like),
            )
        )

    batch = args.get("batch")
    if batch:
        q = q.filter(Batch.batch_name == batch)

    passing_year = args.get("passing_year")
    if passing_year:
        q = q.filter(EmbaDetails.passing_year == int(passing_year))

    industry = args.get("industry")
    if industry:
        q = q.filter(Industry.name == industry)

    blood_group = args.get("blood_group")
    if blood_group:
        q = q.filter(Profile.blood_group == blood_group)

    location = args.get("location")
    if location:
        q = q.filter(Profile.location.ilike(f"%{location}%"))

    return q


def _apply_sort(q, sort):
    if sort == "name":
        return q.order_by(asc(User.name))
    if sort == "batch":
        return q.order_by(asc(Batch.batch_name))
    if sort == "company":
        return q.order_by(asc(Company.name))
    if sort == "industry":
        return q.order_by(asc(Industry.name))

    # default: most active in last 7 days -> recently searched -> registration date (older first)
    since = datetime.utcnow() - timedelta(days=7)
    own_activity = (
        db.session.query(MemberActivity.user_id, func.count(MemberActivity.id).label("score"))
        .filter(MemberActivity.created_at >= since)
        .group_by(MemberActivity.user_id)
        .subquery()
    )
    searched = (
        db.session.query(MemberActivity.target_user_id.label("user_id"), func.count(MemberActivity.id).label("score"))
        .filter(MemberActivity.action == "search_click")
        .group_by(MemberActivity.target_user_id)
        .subquery()
    )
    q = q.outerjoin(own_activity, own_activity.c.user_id == User.id)
    q = q.outerjoin(searched, searched.c.user_id == User.id)
    return q.order_by(
        desc(func.coalesce(own_activity.c.score, 0)),
        desc(func.coalesce(searched.c.score, 0)),
        asc(User.created_at),
    )


def _card_json(user):
    profile = user.profile
    details = user.emba_details
    return {
        "id": user.id,
        "name": user.name,
        "batch": details.batch.batch_name if details and details.batch else None,
        "company": profile.current_company.name if profile and profile.current_company else None,
        "designation": profile.current_designation if profile else None,
        "years_experience": profile.years_of_experience() if profile else None,
        "industry": ", ".join(i.name for i in profile.industries) if profile and profile.industries else None,
        "photo_url": url_for("static", filename="uploads/photos/" + profile.photo_filename) if profile and profile.photo_filename else None,
        "detail_url": url_for("directory.profile_detail", user_id=user.id),
        "contact_url": url_for("directory.api_profile", user_id=user.id),
    }


@directory_bp.route("/directory")
@login_required
@requires_paid_access
def list_view():
    batches = Batch.query.order_by(Batch.batch_name).all()
    industries = Industry.query.order_by(Industry.name).all()
    passing_years = [r[0] for r in db.session.query(EmbaDetails.passing_year).filter(EmbaDetails.passing_year.isnot(None)).distinct().order_by(EmbaDetails.passing_year).all()]
    locations = [r[0] for r in db.session.query(Profile.location).filter(Profile.location.isnot(None), Profile.location != "").distinct().order_by(Profile.location).all()]
    return render_template(
        "directory/list.html",
        batches=batches,
        industries=industries,
        passing_years=passing_years,
        locations=locations,
    )


@directory_bp.route("/api/directory")
@login_required
@requires_paid_access
@limiter.limit("120 per hour")
def api_directory():
    limit = 20
    cursor = int(request.args.get("cursor", 0))

    q = _accessible_members_query()
    q = _apply_filters(q, request.args)
    q = _apply_sort(q, request.args.get("sort", ""))

    rows = q.offset(cursor).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    if request.args.get("q", "").strip():
        for u in rows:
            db.session.add(MemberActivity(user_id=current_user.id, action="search_click", target_user_id=u.id))
        db.session.commit()

    return jsonify(
        results=[_card_json(u) for u in rows],
        next_cursor=(cursor + limit) if has_more else None,
    )


@directory_bp.route("/directory/<int:user_id>")
@login_required
@requires_paid_access
def profile_detail(user_id):
    member = db.session.get(User, user_id)
    if not member or member.status != STATUS_ACTIVE or not member.current_access_valid():
        abort(404)

    db.session.add(MemberActivity(user_id=current_user.id, action="profile_view", target_user_id=member.id))
    db.session.commit()

    profile = member.profile
    contacts = visible_mobile_numbers(profile)
    wa_link_map = {c["number"]: wa_link(c["number"]) for c in contacts if c["whatsapp"]}

    return render_template("directory/detail.html", member=member, profile=profile, contacts=contacts, wa_link_map=wa_link_map)


@directory_bp.route("/api/profile/<int:user_id>")
@login_required
@requires_paid_access
@limiter.limit("60 per hour")
def api_profile(user_id):
    member = db.session.get(User, user_id)
    if not member or member.status != STATUS_ACTIVE or not member.current_access_valid():
        abort(404)

    profile = member.profile
    details = member.emba_details
    contacts = visible_mobile_numbers(profile)
    whatsapp_contacts = [c for c in contacts if c["whatsapp"]]

    db.session.add(MemberActivity(user_id=current_user.id, action="profile_view", target_user_id=member.id))
    db.session.commit()

    return jsonify(
        id=member.id,
        name=member.name,
        batch=details.batch.batch_name if details and details.batch else None,
        passing_year=details.passing_year if details else None,
        company=profile.current_company.name if profile and profile.current_company else None,
        designation=profile.current_designation if profile else None,
        location=profile.location if profile else None,
        blood_group=profile.blood_group if profile else None,
        years_experience=profile.years_of_experience() if profile else None,
        industries=[i.name for i in profile.industries] if profile else [],
        previous_companies=[wh.company.name for wh in member.work_history],
        photo_url=url_for("static", filename="uploads/photos/" + profile.photo_filename) if profile and profile.photo_filename else None,
        contacts=contacts,
        email=member.email,
        facebook_url=profile.facebook_url if profile else None,
        linkedin_url=profile.linkedin_url if profile else None,
        whatsapp_url=wa_link(whatsapp_contacts[0]["number"]) if whatsapp_contacts else None,
    )
