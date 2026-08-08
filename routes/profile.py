from flask import Blueprint, render_template, session
from routes.guards import role_required
from database import get_db
from services.learner_profile_engine import learner_profile
from services.evaluation_dataset import linked_learner_evaluation_evidence

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile")
@role_required("learner")
def profile():
    conn = get_db()
    data = learner_profile(conn, session["user_id"])
    data["evaluation_evidence"] = linked_learner_evaluation_evidence(
        conn, session["user_id"]
    )
    conn.close()
    return render_template("student/profile.html", **data)
