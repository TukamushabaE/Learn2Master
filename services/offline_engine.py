"""Offline support foundation for low-resource deployment.
The prototype records offline-capable events in offline_sync_queue.
"""
import json

def queue_offline_event(conn, learner_id, event_type, payload):
    conn.execute("""
        INSERT INTO offline_sync_queue (learner_id, event_type, payload, sync_status)
        VALUES (?, ?, ?, 'Pending')
    """, (learner_id, event_type, json.dumps(payload)))


def sync_summary(conn):
    rows = conn.execute("""
        SELECT sync_status, COUNT(*) AS total
        FROM offline_sync_queue
        GROUP BY sync_status
    """).fetchall()
    return {row['sync_status']: row['total'] for row in rows}
