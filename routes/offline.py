from flask import Blueprint, jsonify, render_template, request, session, redirect, url_for, flash

from database import get_db
from routes.guards import role_required
from security import csrf_protect
from services.offline_engine import offline_dashboard_data, record_sync_event

offline_bp = Blueprint("offline", __name__)


@offline_bp.route("/offline/status")
@role_required("learner", "teacher", "school_admin", "super_admin")
def status():
    conn = get_db()
    data = offline_dashboard_data(conn)
    conn.close()
    if request.args.get("format") == "json":
        return jsonify({
            "summary": data["summary"],
            "cached_resources": [dict(row) for row in data["cached_resources"]],
            "queue": [dict(row) for row in data["queue"]],
            "events": [dict(row) for row in data["events"]],
        })
    return render_template("offline/status.html", **data)


@offline_bp.route("/offline/sync-queue")
@role_required("learner", "teacher", "school_admin", "super_admin")
def sync_queue():
    conn = get_db()
    data = offline_dashboard_data(conn)
    conn.close()
    return render_template("offline/sync_queue.html", **data)


@offline_bp.route("/offline/sync-queue/<int:queue_id>/<action>", methods=["POST"])
@role_required("teacher", "school_admin", "super_admin")
@csrf_protect
def update_sync_queue(queue_id, action):
    if action not in {"synced", "failed"}:
        flash("Unsupported sync action.", "danger")
        return redirect(url_for("offline.sync_queue"))

    status_value = "Synced" if action == "synced" else "Failed"
    conn = get_db()
    queued = conn.execute("SELECT * FROM sync_queue WHERE queue_id=?", (queue_id,)).fetchone()
    if not queued:
        conn.close()
        flash("Sync item was not found.", "warning")
        return redirect(url_for("offline.sync_queue"))

    conn.execute("""
        UPDATE sync_queue
        SET sync_status=?,
            attempts=attempts + 1,
            last_attempt_at=CURRENT_TIMESTAMP,
            synced_at=CASE WHEN ?='Synced' THEN CURRENT_TIMESTAMP ELSE synced_at END,
            error_message=CASE WHEN ?='Failed' THEN ? ELSE NULL END
        WHERE queue_id=?
    """, (
        status_value,
        status_value,
        status_value,
        request.form.get("error_message") or "Manual prototype sync failure record.",
        queue_id,
    ))
    learner_match = "learner_id IS NULL" if queued["learner_id"] is None else "learner_id=?"
    learner_params = () if queued["learner_id"] is None else (queued["learner_id"],)
    conn.execute(f"""
        UPDATE offline_sync_queue
        SET sync_status=?,
            synced_at=CASE WHEN ?='Synced' THEN CURRENT_TIMESTAMP ELSE synced_at END,
            last_error=CASE WHEN ?='Failed' THEN ? ELSE NULL END
        WHERE {learner_match}
          AND event_type=?
          AND payload=?
          AND sync_status='Pending'
    """, (
        status_value,
        status_value,
        status_value,
        request.form.get("error_message") or "Manual prototype sync failure record.",
        *learner_params,
        queued["queue_type"],
        queued["payload"],
    ))
    record_sync_event(
        conn,
        session.get("user_id"),
        "manual_sync",
        status_value,
        queued_count=1,
        synced_count=1 if status_value == "Synced" else 0,
        failed_count=1 if status_value == "Failed" else 0,
        details=f"Queue item {queue_id} marked {status_value}.",
    )
    conn.execute("""
        INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details)
        VALUES (?, 'SYNC_ATTEMPT', 'sync_queue', ?, ?)
    """, (session.get("user_id"), queue_id, f"Manual offline sync status: {status_value}"))
    conn.commit()
    conn.close()
    flash(f"Sync item marked {status_value}.", "success")
    return redirect(url_for("offline.sync_queue"))


@offline_bp.route("/admin/sync-logs")
@role_required("school_admin", "super_admin")
def admin_sync_logs():
    conn = get_db()
    data = offline_dashboard_data(conn)
    conn.close()
    return render_template("admin/sync_logs.html", **data)
