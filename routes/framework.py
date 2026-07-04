from flask import Blueprint, render_template
from routes.guards import role_required
from database import get_db
from services.framework_alignment import get_alignment_matrix, get_evaluation_matrix
from services.analytics_engine import framework_metrics

framework_bp = Blueprint("framework", __name__)


@framework_bp.route("/framework/alignment")
@role_required("teacher", "school_admin", "super_admin")
def alignment():
    conn = get_db()
    metrics = framework_metrics(conn)
    conn.close()
    return render_template(
        "framework/alignment.html",
        components=get_alignment_matrix(),
        indicators=get_evaluation_matrix(),
        metrics=metrics,
    )
