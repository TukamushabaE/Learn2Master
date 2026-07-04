from flask import Blueprint, render_template, session
from routes.guards import role_required
from database import get_db
from services.learner_profile_engine import learner_profile

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile")
@role_required("learner")
def profile():
    conn = get_db()
    data = learner_profile(conn, session["user_id"])
    conn.close()
    return render_template("student/profile.html", **data)
