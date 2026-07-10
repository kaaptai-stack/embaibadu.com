import secrets
from datetime import datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db

# --- constant "enums" (plain strings, kept simple for SQLite) ---
ROLE_MEMBER = "member"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"
ROLES = [ROLE_MEMBER, ROLE_ADMIN, ROLE_SUPER_ADMIN]

STATUS_UNREGISTERED = "unregistered"  # preloaded roster row; not a real account until claimed
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_INACTIVE = "inactive"
STATUS_BLOCKED = "blocked"
STATUS_REJECTED = "rejected"

REFERRAL_PENDING = "pending"
REFERRAL_USED = "used"
REFERRAL_EXPIRED = "expired"

PAYMENT_INITIATED = "initiated"
PAYMENT_SUCCESS = "success"
PAYMENT_FAILED = "failed"
PAYMENT_REFUNDED = "refunded"

PAYMENT_TYPES = ["registration fee", "annual subscription", "event", "donation"]
PAYMENT_METHODS = ["cash", "bkash", "bank transfer", "card"]

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_MEMBER)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)

    referred_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    referred_by = db.relationship("User", remote_side=[id])

    email_verified_at = db.Column(db.DateTime, nullable=True)
    last_active_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rejection_reason = db.Column(db.String(500), nullable=True)

    profile = db.relationship("Profile", uselist=False, back_populates="user", cascade="all, delete-orphan")
    emba_details = db.relationship("EmbaDetails", uselist=False, back_populates="user", cascade="all, delete-orphan")
    work_history = db.relationship("WorkHistory", back_populates="user", cascade="all, delete-orphan", order_by="WorkHistory.sort_order")
    payments = db.relationship("Payment", foreign_keys="Payment.user_id", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def is_active_status(self):
        return self.status == STATUS_ACTIVE

    # flask-login: block login for blocked/inactive/pending/rejected accounts
    @property
    def is_active(self):
        return self.status == STATUS_ACTIVE

    def current_access_valid(self):
        latest = (
            Payment.query.filter_by(user_id=self.id, status=PAYMENT_SUCCESS)
            .order_by(Payment.valid_until.desc())
            .first()
        )
        if not latest or not latest.valid_until:
            return False
        return latest.valid_until >= datetime.utcnow().date()

    def access_valid_until(self):
        latest = (
            Payment.query.filter_by(user_id=self.id, status=PAYMENT_SUCCESS)
            .order_by(Payment.valid_until.desc())
            .first()
        )
        return latest.valid_until if latest else None


class Referral(db.Model):
    __tablename__ = "referrals"

    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    referrer = db.relationship("User", foreign_keys=[referrer_id])
    token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(24))
    invitee_email = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default=REFERRAL_PENDING)
    expires_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.utcnow() + timedelta(days=7))
    used_at = db.Column(db.DateTime, nullable=True)
    registered_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    def is_valid(self):
        return self.status == REFERRAL_PENDING and self.expires_at >= datetime.utcnow()


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    flagged_for_review = db.Column(db.Boolean, default=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)


class Industry(db.Model):
    __tablename__ = "industries"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)


profile_industries = db.Table(
    "profile_industries",
    db.Column("user_id", db.Integer, db.ForeignKey("profiles.user_id"), primary_key=True),
    db.Column("industry_id", db.Integer, db.ForeignKey("industries.id"), primary_key=True),
)


class Profile(db.Model):
    __tablename__ = "profiles"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    user = db.relationship("User", back_populates="profile")

    mobile_personal = db.Column(db.String(30), nullable=True)
    mobile_personal_whatsapp = db.Column(db.Boolean, default=False)
    mobile_personal_hide = db.Column(db.Boolean, default=False)

    mobile_office = db.Column(db.String(30), nullable=True)
    mobile_office_whatsapp = db.Column(db.Boolean, default=False)
    mobile_office_hide = db.Column(db.Boolean, default=False)

    facebook_url = db.Column(db.String(500), nullable=True)
    linkedin_url = db.Column(db.String(500), nullable=True)

    current_company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True)
    current_company = db.relationship("Company")
    current_designation = db.Column(db.String(200), nullable=True)
    career_start_year = db.Column(db.Integer, nullable=True)

    blood_group = db.Column(db.String(5), nullable=True)
    location = db.Column(db.String(150), nullable=True)

    photo_filename = db.Column(db.String(255), nullable=True)
    banner_filename = db.Column(db.String(255), nullable=True)

    industries = db.relationship("Industry", secondary=profile_industries, backref="profiles")

    def years_of_experience(self):
        if not self.career_start_year:
            return None
        return max(0, datetime.utcnow().year - self.career_start_year)


class WorkHistory(db.Model):
    __tablename__ = "work_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user = db.relationship("User", back_populates="work_history")
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    company = db.relationship("Company")
    sort_order = db.Column(db.Integer, default=0)


class Batch(db.Model):
    __tablename__ = "batches"

    id = db.Column(db.Integer, primary_key=True)
    batch_name = db.Column(db.String(50), unique=True, nullable=False)
    passing_year = db.Column(db.Integer, nullable=True)
    passing_year_placeholder = db.Column(db.Boolean, default=False)


class EmbaDetails(db.Model):
    __tablename__ = "emba_details"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    user = db.relationship("User", back_populates="emba_details")
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), nullable=True)
    batch = db.relationship("Batch")
    passing_year = db.Column(db.Integer, nullable=True)
    class_roll = db.Column(db.String(50), nullable=True)


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user = db.relationship("User", foreign_keys=[user_id], back_populates="payments")

    amount = db.Column(db.Float, nullable=False)
    payment_type = db.Column(db.String(50), nullable=False)
    method = db.Column(db.String(50), nullable=False)
    gateway = db.Column(db.String(50), nullable=True)
    gateway_txn_id = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), nullable=False, default=PAYMENT_INITIATED)
    reference_no = db.Column(db.String(100), nullable=True)
    note = db.Column(db.String(500), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    valid_until = db.Column(db.Date, nullable=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    recorded_by_user = db.relationship("User", foreign_keys=[recorded_by])
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MemberActivity(db.Model):
    __tablename__ = "member_activity"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(30), nullable=False)  # login / profile_view / search_click
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ActivityLog(db.Model):
    __tablename__ = "activity_log"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    admin = db.relationship("User", foreign_keys=[admin_id])
    action = db.Column(db.String(100), nullable=False)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    details = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Announcement(db.Model):
    __tablename__ = "announcements"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    active = db.Column(db.Boolean, default=True)


class DevEmail(db.Model):
    """Mock outbox — stands in for real SMTP so email flows are testable locally."""

    __tablename__ = "dev_emails"

    id = db.Column(db.Integer, primary_key=True)
    to_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body_html = db.Column(db.Text, nullable=False)
    link_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
