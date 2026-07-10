import secrets
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, abort, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models import DevEmail, Payment, PAYMENT_SUCCESS, PAYMENT_FAILED, PAYMENT_INITIATED

devtools_bp = Blueprint("devtools", __name__)

ACCESS_FEE_AMOUNT = 1000.0
ACCESS_VALIDITY_DAYS = 365


@devtools_bp.route("/inbox")
def inbox():
    emails = DevEmail.query.order_by(DevEmail.created_at.desc()).limit(100).all()
    return render_template("devtools/inbox.html", emails=emails)


@devtools_bp.route("/inbox/<int:email_id>")
def inbox_detail(email_id):
    email = db.session.get(DevEmail, email_id)
    if not email:
        abort(404)
    return render_template("devtools/inbox_detail.html", email=email)


@devtools_bp.route("/payment/checkout", methods=["POST"])
@login_required
def payment_checkout():
    has_prior = Payment.query.filter_by(user_id=current_user.id, status=PAYMENT_SUCCESS).first()
    payment_type = "annual subscription" if has_prior else "registration fee"

    payment = Payment(
        user_id=current_user.id,
        amount=ACCESS_FEE_AMOUNT,
        payment_type=payment_type,
        method="bkash",
        gateway="mock-bkash",
        status=PAYMENT_INITIATED,
    )
    db.session.add(payment)
    db.session.commit()
    return redirect(url_for("devtools.payment_mock", payment_id=payment.id))


@devtools_bp.route("/payment/mock/<int:payment_id>")
@login_required
def payment_mock(payment_id):
    payment = db.session.get(Payment, payment_id)
    if not payment or payment.user_id != current_user.id:
        abort(404)
    return render_template("devtools/payment_mock.html", payment=payment)


@devtools_bp.route("/payment/mock/<int:payment_id>/complete", methods=["POST"])
@login_required
def payment_complete(payment_id):
    payment = db.session.get(Payment, payment_id)
    if not payment or payment.user_id != current_user.id:
        abort(404)

    outcome = request.form.get("outcome")
    # This simulates the gateway's server-to-server IPN callback landing on our backend.
    txn_id = "MOCKTXN" + secrets.token_hex(6).upper()
    if outcome == "success":
        payment.status = PAYMENT_SUCCESS
        payment.gateway_txn_id = txn_id
        payment.reference_no = txn_id
        payment.paid_at = datetime.utcnow()
        payment.valid_until = (datetime.utcnow() + timedelta(days=ACCESS_VALIDITY_DAYS)).date()
        db.session.commit()
        flash("Payment successful — your directory access is now unlocked.", "success")
    else:
        payment.status = PAYMENT_FAILED
        payment.gateway_txn_id = txn_id
        db.session.commit()
        flash("Payment failed. Please try again.", "error")

    return redirect(url_for("member.dashboard"))
