import secrets
from functools import wraps

from flask import abort, current_app, request, session


def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf_token():
    if not current_app.config.get("CSRF_ENABLED", True):
        return
    expected = session.get("_csrf_token")
    submitted = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        abort(400, description="Invalid or missing CSRF token.")


def csrf_protect(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            validate_csrf_token()
        return view(*args, **kwargs)
    return wrapped_view
