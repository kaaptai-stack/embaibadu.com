import os
import re
import secrets
import uuid
from datetime import datetime
from functools import wraps

from flask import abort, current_app, url_for
from flask_login import current_user

from app.extensions import db
from app.models import DevEmail, ActivityLog, ROLE_ADMIN, ROLE_SUPER_ADMIN


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def admin_required(view):
    return role_required(ROLE_ADMIN, ROLE_SUPER_ADMIN)(view)


def super_admin_required(view):
    return role_required(ROLE_SUPER_ADMIN)(view)


def requires_paid_access(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
            return view(*args, **kwargs)
        if not current_user.current_access_valid():
            from flask import redirect

            return redirect(url_for("member.dashboard"))
        return view(*args, **kwargs)

    return wrapped


def send_dev_email(to_email, subject, body_html, link_url=None):
    """Mock SMTP: records the 'sent' email in the DB Dev Inbox instead of a real send."""
    email = DevEmail(to_email=to_email, subject=subject, body_html=body_html, link_url=link_url)
    db.session.add(email)
    db.session.commit()
    return email


def log_admin_action(action, target_user_id=None, details=None):
    entry = ActivityLog(
        admin_id=current_user.id,
        action=action,
        target_user_id=target_user_id,
        details=details,
    )
    db.session.add(entry)
    db.session.commit()


def allowed_image(filename, ext_set):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ext_set


def save_upload(file_storage, subfolder):
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    file_storage.save(path)
    return filename


PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$")


def is_strong_password(pw):
    return bool(PASSWORD_RE.match(pw or ""))


def normalize_company_name(name):
    return " ".join(name.strip().split())


def visible_mobile_numbers(profile):
    """Numbers the member hasn't hidden, each flagged with its own WhatsApp toggle."""
    contacts = []
    if not profile:
        return contacts
    if profile.mobile_personal and not profile.mobile_personal_hide:
        contacts.append({"label": "Personal", "number": profile.mobile_personal, "whatsapp": bool(profile.mobile_personal_whatsapp)})
    if profile.mobile_office and not profile.mobile_office_hide:
        contacts.append({"label": "Office", "number": profile.mobile_office, "whatsapp": bool(profile.mobile_office_whatsapp)})
    return contacts


def wa_link(mobile):
    digits = re.sub(r"\D", "", mobile or "")
    if digits.startswith("0"):
        digits = "88" + digits
    elif not digits.startswith("880"):
        digits = "880" + digits
    return f"https://wa.me/{digits}"


def new_token():
    return secrets.token_urlsafe(32)


def get_serializer():
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def make_timed_token(payload, salt):
    return get_serializer().dumps(payload, salt=salt)


def read_timed_token(token, salt, max_age):
    try:
        return get_serializer().loads(token, salt=salt, max_age=max_age)
    except Exception:
        return None
