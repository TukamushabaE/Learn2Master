from functools import wraps
from flask import session, redirect, url_for, flash

SUPER_ADMIN = "super_admin"


def role_home_endpoint(role):
    if role == "learner":
        return "student.student_dashboard"
    if role == "teacher":
        return "teacher.teacher_dashboard"
    if role in {"school_admin", "super_admin"}:
        return "admin.admin_dashboard"
    return "auth.home"


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("auth.home"))
        return view(*args, **kwargs)
    return wrapped_view


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if "user_id" not in session:
                flash("Please login first.", "warning")
                return redirect(url_for("auth.home"))

            current_role = session.get("role")
            if current_role != SUPER_ADMIN and current_role not in roles:
                flash("You are not allowed to access that page.", "danger")
                return redirect(url_for(role_home_endpoint(current_role)))

            return view(*args, **kwargs)
        return wrapped_view
    return decorator
