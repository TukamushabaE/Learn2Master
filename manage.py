import argparse
import os
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash

import init_db
from models import db, Role, School, User


ROLE_DISPLAY_NAMES = {
    "super_admin": "Super Administrator",
    "school_admin": "School Administrator",
    "teacher": "Teacher",
    "learner": "Learner",
}

BOOTSTRAP_USERS = (
    ("super_admin", "LEARN2MASTER_SUPER_ADMIN", 5, "Super Administrator"),
    ("school_admin", "LEARN2MASTER_SCHOOL_ADMIN", 4, "School Administrator"),
    ("teacher", "LEARN2MASTER_TEACHER", 3, "Teacher"),
)


def required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value


def optional_env(name, default=None):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def ensure_role(role_name):
    role = Role.query.filter_by(role_name=role_name).first()
    if not role:
        role = Role(role_name=role_name, display_name=ROLE_DISPLAY_NAMES[role_name])
        db.session.add(role)
        db.session.flush()
    return role


def ensure_school():
    school_name = required_env("LEARN2MASTER_BOOTSTRAP_SCHOOL_NAME")
    school = School.query.filter_by(school_name=school_name).first()
    if not school:
        school = School(school_name=school_name)
        db.session.add(school)
        db.session.flush()
    return school


def create_or_preserve_user(role_name, prefix, security_level, default_title, school, update_passwords=False):
    role = ensure_role(role_name)
    username = required_env(f"{prefix}_USERNAME")
    email = required_env(f"{prefix}_EMAIL")
    full_name = required_env(f"{prefix}_FULL_NAME")
    password = required_env(f"{prefix}_PASSWORD")

    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(
            full_name=full_name,
            username=username,
            email=email,
            title=optional_env(f"{prefix}_TITLE", default_title),
            password_hash=generate_password_hash(password),
            role_id=role.role_id,
            school_id=school.school_id,
            account_status="Active",
            security_level=security_level,
            must_change_password=0,
            approved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.session.add(user)
        action = "created"
    else:
        user.full_name = full_name
        user.email = email
        user.title = optional_env(f"{prefix}_TITLE", user.title or default_title)
        user.role_id = role.role_id
        user.school_id = school.school_id
        user.account_status = "Active"
        user.security_level = security_level
        if update_passwords:
            user.password_hash = generate_password_hash(password)
            user.must_change_password = 0
        action = "updated" if update_passwords else "preserved"

    db.session.flush()
    return user, action


def create_initial_users(update_passwords=False):
    from app import app

    with app.app_context():
        school = ensure_school()
        results = []
        for role_name, prefix, security_level, title in BOOTSTRAP_USERS:
            user, action = create_or_preserve_user(
                role_name,
                prefix,
                security_level,
                title,
                school,
                update_passwords=update_passwords,
            )
            results.append((user.username, role_name, action))
        db.session.commit()
        return results


def main():
    parser = argparse.ArgumentParser(description="Learn2Master secure management commands.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    init_parser = subcommands.add_parser("init-db", help="Initialize the configured database idempotently.")
    init_parser.add_argument("--reset", action="store_true", help="Drop tables first. Use only for local/dev test databases.")

    seed_parser = subcommands.add_parser("seed-demo-data", help="Seed CBC demo content using environment-provided passwords.")
    seed_parser.set_defaults(seed_demo=True)

    users_parser = subcommands.add_parser("create-initial-users", help="Create the first super admin, school admin, and teacher.")
    users_parser.add_argument("--update-passwords", action="store_true", help="Rotate passwords for existing bootstrap users from env vars.")

    args = parser.parse_args()

    if args.command == "init-db":
        db_url = os.environ.get("DATABASE_URL")
        if init_db.is_postgres_url(db_url):
            init_db.run_postgres(db_url, reset=args.reset)
        else:
            init_db.run_sqlite(db_path=init_db.sqlite_path_from_url(db_url), reset=args.reset)
        return

    if args.command == "seed-demo-data":
        import seed_data  # noqa: F401 - module execution performs idempotent seed.
        return

    if args.command == "create-initial-users":
        results = create_initial_users(update_passwords=args.update_passwords)
        for username, role_name, action in results:
            print(f"{role_name}: {username} {action}")


if __name__ == "__main__":
    main()
