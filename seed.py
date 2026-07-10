"""
Initializes a clean database: EMBA batches plus the Super Admin and Admin
accounts only. No member data is preloaded or imported from the spreadsheet —
the admin is expected to add the first real members themselves (Admin > Users
> Add member, or Admin > Users > Bulk import using EMBA Database.xlsx), who
can then use Refer to invite further members.

Re-run any time after deleting instance/emba.db to reset to this clean state
(this permanently drops and recreates every table).
"""
from datetime import datetime

from app import create_app
from app.extensions import db
from app.models import User, Batch, ROLE_ADMIN, ROLE_SUPER_ADMIN, STATUS_ACTIVE

ADMIN_PASSWORD = "AdminPass123!"


def seed_batches():
    base_year = 2004  # placeholder baseline; correct actual passing years under Admin > Batches
    for n in range(1, 44):
        db.session.add(Batch(
            batch_name=f"Batch {n}",
            passing_year=base_year + (n - 1) // 2,
            passing_year_placeholder=True,
        ))
    db.session.flush()


def main():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        print("Seeding batches 1-43 (placeholder passing years, flagged for admin correction)...")
        seed_batches()

        print("Creating Super Admin and Admin accounts...")
        super_admin = User(
            name="Association Super Admin", email="superadmin@embaiba.org",
            role=ROLE_SUPER_ADMIN, status=STATUS_ACTIVE, email_verified_at=datetime.utcnow(),
        )
        super_admin.set_password(ADMIN_PASSWORD)
        admin = User(
            name="Association Admin", email="admin@embaiba.org",
            role=ROLE_ADMIN, status=STATUS_ACTIVE, email_verified_at=datetime.utcnow(),
        )
        admin.set_password(ADMIN_PASSWORD)
        db.session.add_all([super_admin, admin])
        db.session.commit()

        print("\n=== Database initialized ===")
        print("No member data exists — nothing was imported from the spreadsheet.")
        print("Log in as an admin and add the first members under Admin > Users > Add member,")
        print("or Admin > Users > Bulk import (EMBA Database.xlsx uses columns: name, batch, roll, mobile, email).")
        print(f"\n  Admin:        admin@embaiba.org / {ADMIN_PASSWORD}")
        print(f"  Super Admin:  superadmin@embaiba.org / {ADMIN_PASSWORD}")


if __name__ == "__main__":
    main()
