from collections import Counter


def safe_percent(numerator, denominator):
    if not denominator:
        return 0
    return round((numerator / denominator) * 100, 1)


def teacher_overview(conn):
    learners = conn.execute("""
        SELECT COUNT(*) AS total
        FROM users u
        JOIN roles r ON u.role_id = r.role_id
        WHERE r.role_name = 'learner'
    """).fetchone()["total"]

    records = conn.execute("""
        SELECT mr.*, u.full_name, lo.outcome_name
        FROM mastery_records mr
        JOIN users u ON mr.learner_id = u.user_id
        JOIN learning_outcomes lo ON mr.outcome_id = lo.outcome_id
    """).fetchall()

    mastered = sum(1 for r in records if r["mastery_status"] == "Mastered")
    at_risk = sum(1 for r in records if r["mastery_status"] != "Mastered" and (r["posttest_score"] or r["practice_score"] or r["pretest_score"]) > 0)
    avg_mastery = round(sum(r["mastery_score"] for r in records) / len(records), 1) if records else 0

    pending_recs = conn.execute("""
        SELECT COUNT(*) AS total FROM recommendations
        WHERE teacher_status = 'Pending Review'
    """).fetchone()["total"]

    concept_rows = conn.execute("""
        SELECT concept_tag, latest_score
        FROM concept_mastery
        WHERE latest_score < 70
    """).fetchall()
    weak_counter = Counter(row["concept_tag"] for row in concept_rows)
    common_weak = weak_counter.most_common(1)[0][0].replace('_', ' ').title() if weak_counter else "None currently"

    return {
        "learners": learners,
        "records": records,
        "mastered": mastered,
        "at_risk": at_risk,
        "avg_mastery": avg_mastery,
        "pending_recs": pending_recs,
        "mastery_rate": safe_percent(mastered, len(records)),
        "common_weak": common_weak,
    }


def recent_ai_recommendations(conn, limit=8):
    return conn.execute("""
        SELECT rec.*, u.full_name, lo.outcome_name
        FROM recommendations rec
        JOIN users u ON rec.learner_id = u.user_id
        JOIN learning_outcomes lo ON rec.outcome_id = lo.outcome_id
        ORDER BY rec.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()


def framework_metrics(conn):
    total_outcomes = conn.execute("SELECT COUNT(*) AS total FROM learning_outcomes").fetchone()["total"]
    total_recs = conn.execute("SELECT COUNT(*) AS total FROM recommendations").fetchone()["total"]
    total_attempts = conn.execute("SELECT COUNT(*) AS total FROM assessment_attempts").fetchone()["total"]
    mastered = conn.execute("SELECT COUNT(*) AS total FROM mastery_records WHERE mastery_status = 'Mastered'").fetchone()["total"]
    records = conn.execute("SELECT COUNT(*) AS total FROM mastery_records").fetchone()["total"]
    return {
        "total_outcomes": total_outcomes,
        "total_recommendations": total_recs,
        "total_attempts": total_attempts,
        "mastered_records": mastered,
        "mastery_rate": safe_percent(mastered, records),
    }
