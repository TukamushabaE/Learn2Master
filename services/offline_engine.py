"""Offline support foundation for low-resource deployment.

The prototype does not attempt full production background sync. It records
cacheable resources, queued learner events and sync attempts so evaluators can
see how Learn2Master would behave in low-connectivity schools.
"""
import json


def queue_offline_event(conn, learner_id, event_type, payload, actor_id=None):
    encoded = json.dumps(payload)
    conn.execute("""
        INSERT INTO offline_sync_queue (learner_id, event_type, payload, sync_status)
        VALUES (?, ?, ?, 'Pending')
    """, (learner_id, event_type, encoded))
    conn.execute("""
        INSERT INTO sync_queue (learner_id, queue_type, payload, sync_status)
        VALUES (?, ?, ?, 'Pending')
    """, (learner_id, event_type, encoded))
    conn.execute("""
        INSERT INTO offline_activity_logs (actor_id, action, details, offline_status)
        VALUES (?, ?, ?, 'Pending Sync')
    """, (actor_id or learner_id, f"QUEUE_{event_type.upper()}", encoded))


def mark_cached_resource(conn, resource_type, resource_id, title, cache_key, size_kb=0):
    conn.execute("""
        INSERT INTO cached_resources
        (resource_type, resource_id, resource_title, cache_key, cache_status, estimated_size_kb)
        VALUES (?, ?, ?, ?, 'Cached', ?)
        ON CONFLICT(cache_key)
        DO UPDATE SET cache_status='Cached', last_checked_at=CURRENT_TIMESTAMP
    """, (resource_type, resource_id, title, cache_key, size_kb))


def record_sync_event(conn, actor_id, event_type, status, queued_count=0, synced_count=0, failed_count=0, details=None):
    conn.execute("""
        INSERT INTO sync_events
        (actor_id, event_type, event_status, queued_count, synced_count, failed_count, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (actor_id, event_type, status, queued_count, synced_count, failed_count, details))


def sync_summary(conn):
    queue_rows = conn.execute("""
        SELECT sync_status, COUNT(*) AS total
        FROM sync_queue
        GROUP BY sync_status
    """).fetchall()
    cached = conn.execute("SELECT COUNT(*) AS total FROM cached_resources WHERE cache_status='Cached'").fetchone()
    events = conn.execute("SELECT COUNT(*) AS total FROM sync_events").fetchone()
    summary = {row["sync_status"]: row["total"] for row in queue_rows}
    summary["Cached"] = cached["total"] if cached else 0
    summary["Events"] = events["total"] if events else 0
    return summary


def offline_dashboard_data(conn):
    return {
        "summary": sync_summary(conn),
        "cached_resources": conn.execute("""
            SELECT *
            FROM cached_resources
            ORDER BY last_checked_at DESC, created_at DESC
            LIMIT 80
        """).fetchall(),
        "queue": conn.execute("""
            SELECT sq.*, learner.full_name AS learner_name
            FROM sync_queue sq
            LEFT JOIN users learner ON learner.user_id = sq.learner_id
            ORDER BY sq.created_at DESC
            LIMIT 80
        """).fetchall(),
        "events": conn.execute("""
            SELECT se.*, actor.full_name AS actor_name
            FROM sync_events se
            LEFT JOIN users actor ON actor.user_id = se.actor_id
            ORDER BY se.attempted_at DESC
            LIMIT 80
        """).fetchall(),
    }
