from flask import Blueprint, render_template, request, redirect, session, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone
import sqlite3

from database import get_db
from models import db, User
from security import csrf_protect
from routes.guards import role_home_endpoint
from extensions import limiter

auth_bp = Blueprint("auth", __name__)

def password_meets_policy(password):
    password = password or ""
    return (
        len(password) >= 8
        and any(ch.isalpha() for ch in password)
        and any(ch.isdigit() for ch in password)
    )

def record_auth_audit(conn, user_id, action, details):
    conn.execute("""
        INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details)
        VALUES (?, ?, 'user', ?, ?)
    """, (user_id, action, str(user_id), details))

@auth_bp.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for(role_home_endpoint(session.get("role"))))
    return redirect(url_for("auth.login_view"))

@auth_bp.route("/login", methods=["GET"])
def login_view():
    return render_template("login.html")

@auth_bp.route("/login", methods=["POST"])
@csrf_protect
@limiter.limit("5 per minute")
def login():
    username = request.form.get("username")
    password = request.form.get("password")

    conn = get_db()

    user = conn.execute("""
        SELECT users.*, roles.role_name, schools.school_name
        FROM users
        JOIN roles ON users.role_id = roles.role_id
        LEFT JOIN schools ON users.school_id = schools.school_id
        WHERE users.username = ?
    """, (username,)).fetchone()

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if user:
        locked_until = user["locked_until"]
        if user["account_status"] == "Locked" and locked_until and datetime.fromisoformat(locked_until) <= now:
            conn.execute("""
                UPDATE users
                SET account_status = 'Active',
                    failed_login_attempts = 0,
                    locked_until = NULL
                WHERE user_id = ?
            """, (user["user_id"],))
            conn.commit()
            user = conn.execute("""
                SELECT users.*, roles.role_name, schools.school_name
                FROM users
                JOIN roles ON users.role_id = roles.role_id
                LEFT JOIN schools ON users.school_id = schools.school_id
                WHERE users.user_id = ?
            """, (user["user_id"],)).fetchone()
            locked_until = None
        if user["account_status"] != "Active":
            conn.close()
            flash("This account is not active. Contact a school administrator.", "danger")
            return redirect(url_for("auth.home"))
        if locked_until and datetime.fromisoformat(locked_until) > now:
            conn.close()
            flash("This account is temporarily locked after repeated failed attempts.", "danger")
            return redirect(url_for("auth.home"))

    if user and check_password_hash(user["password_hash"], password):
        conn.execute("""
            UPDATE users
            SET failed_login_attempts = 0,
                locked_until = NULL,
                last_login_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (user["user_id"],))
        record_auth_audit(conn, user["user_id"], "LOGIN_SUCCESS", "User logged in successfully")
        conn.commit()
        conn.close()

        user_obj = db.session.get(User, int(user["user_id"]))
        if not user_obj:
            user_obj = User.query.filter_by(id=int(user["user_id"])).first()

        if user_obj:
            login_user(user_obj)

        session["user_id"] = user["user_id"]
        session["username"] = user["username"]
        session["full_name"] = user["full_name"]
        session["role"] = user["role_name"]
        session["must_change_password"] = int(user["must_change_password"] or 0)

        if session["must_change_password"]:
            flash("Please change your temporary password before continuing.", "warning")
            return redirect(url_for("auth.change_password"))

        return redirect(url_for(role_home_endpoint(user["role_name"])))

    if user:
        attempts = int(user["failed_login_attempts"] or 0) + 1
        lock_until = None
        status = user["account_status"]
        if attempts >= 5:
            lock_until = (now + timedelta(minutes=15)).isoformat(timespec="seconds")
            status = "Locked"
        conn.execute("""
            UPDATE users
            SET failed_login_attempts = ?,
                locked_until = ?,
                account_status = ?
            WHERE user_id = ?
        """, (attempts, lock_until, status, user["user_id"]))
        record_auth_audit(conn, user["user_id"], "LOGIN_FAILED", f"Failed login attempt {attempts}")
        conn.commit()
    conn.close()

    flash("Invalid username or password.", "danger")
    return redirect(url_for("auth.home"))

@auth_bp.route("/register", methods=["GET", "POST"])
@csrf_protect
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name")
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        school_name = request.form.get("school_name")
        role_name = "learner"

        if not password_meets_policy(password):
            flash("Password must be at least 8 characters and include letters and numbers.", "danger")
            return redirect(url_for("auth.register"))

        conn = get_db()

        role = conn.execute(
            "SELECT role_id FROM roles WHERE role_name = ?",
            (role_name,)
        ).fetchone()

        school = conn.execute(
            "SELECT school_id FROM schools WHERE school_name = ?",
            (school_name,)
        ).fetchone()

        if not school:
            conn.execute("INSERT INTO schools (school_name) VALUES (?)", (school_name,))
            conn.commit()
            school = conn.execute(
                "SELECT school_id FROM schools WHERE school_name = ?",
                (school_name,)
            ).fetchone()

        try:
            conn.execute("""
                INSERT INTO users
                (full_name, username, email, password_hash, role_id, school_id,
                 account_status, security_level)
                VALUES (?, ?, ?, ?, ?, ?, 'Active', 1)
            """, (
                full_name,
                username,
                email,
                generate_password_hash(password),
                role["role_id"],
                school["school_id"]
            ))
            user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            record_auth_audit(conn, user_id, "REGISTER_LEARNER", "Self-registration created learner account")
            conn.commit()
            flash("Account created successfully. Please login.", "success")
            return redirect(url_for("auth.home"))

        except sqlite3.IntegrityError:
            flash("Username or email already exists.", "danger")
            return redirect(url_for("auth.register"))

        finally:
            conn.close()

    return render_template("register.html")

@auth_bp.route("/change-password", methods=["GET", "POST"])
@csrf_protect
def change_password():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.home"))

    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        if new_password != confirm_password:
            flash("New passwords do not match.", "danger")
            return redirect(url_for("auth.change_password"))
        if not password_meets_policy(new_password):
            flash("Password must be at least 8 characters and include letters and numbers.", "danger")
            return redirect(url_for("auth.change_password"))

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (session["user_id"],)).fetchone()
        if not user or not check_password_hash(user["password_hash"], current_password):
            conn.close()
            flash("Current password is incorrect.", "danger")
            return redirect(url_for("auth.change_password"))

        conn.execute("""
            UPDATE users
            SET password_hash = ?, must_change_password = 0, failed_login_attempts = 0,
                locked_until = NULL, account_status = 'Active'
            WHERE user_id = ?
        """, (generate_password_hash(new_password), session["user_id"]))
        record_auth_audit(conn, session["user_id"], "CHANGE_PASSWORD", "User changed temporary or existing password")
        conn.commit()
        conn.close()

        session["must_change_password"] = 0
        flash("Password updated successfully.", "success")
        return redirect(url_for(role_home_endpoint(session.get("role"))))

    return render_template("change_password.html")


@auth_bp.route("/setup-default-users")
def setup_default_users():
    from werkzeug.security import generate_password_hash

    conn = get_db()

    default_users = [
        ("ICT Physics Teacher", "teacher", "teacher@example.com", "Teacher", "teacher", 3),
        ("School Administrator", "admin", "admin@example.com", "School Administrator", "school_admin", 4),
        ("System Owner", "superadmin", "superadmin@example.com", "Super Administrator", "super_admin", 5),
    ]

    school = conn.execute(
        "SELECT school_id FROM schools WHERE school_name = ?",
        ("Kigezi High School",)
    ).fetchone()

    if not school:
        conn.execute("INSERT INTO schools (school_name) VALUES (?)", ("Kigezi High School",))
        conn.commit()
        school = conn.execute(
            "SELECT school_id FROM schools WHERE school_name = ?",
            ("Kigezi High School",)
        ).fetchone()

    for full_name, username, email, title, role_name, security_level in default_users:
        role = conn.execute(
            "SELECT role_id FROM roles WHERE role_name = ?",
            (role_name,)
        ).fetchone()

        if role:
            conn.execute("""
                INSERT OR IGNORE INTO users
                (full_name, username, email, password_hash, role_id, school_id,
                 title, account_status, security_level, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Active', ?, CURRENT_TIMESTAMP)
            """, (
                full_name,
                username,
                email,
                generate_password_hash("Admin12345"),
                role["role_id"],
                school["school_id"],
                title,
                security_level
            ))

    conn.commit()
    conn.close()

    return "Default teacher/admin users created. REMOVE THIS ROUTE NOW."

@auth_bp.route("/logout")
def logout():
    user_id = session.get("user_id")
    if user_id:
        conn = get_db()
        record_auth_audit(conn, user_id, "LOGOUT", "User logged out")
        conn.commit()
        conn.close()
    logout_user()
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("auth.home"))
