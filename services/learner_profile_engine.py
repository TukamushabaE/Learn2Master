from collections import Counter


def learner_profile(conn, learner_id):
    user = conn.execute("""
        SELECT u.*, s.school_name
        FROM users u
        LEFT JOIN schools s ON u.school_id = s.school_id
        WHERE u.user_id = ?
    """, (learner_id,)).fetchone()

    profile = conn.execute("SELECT * FROM learner_profiles WHERE learner_id = ?", (learner_id,)).fetchone()
    records = conn.execute("""
        SELECT mr.*, lo.outcome_name, c.course_title, sub.subject_name
        FROM mastery_records mr
        JOIN learning_outcomes lo ON mr.outcome_id = lo.outcome_id
        JOIN competencies comp ON lo.competency_id = comp.competency_id
        JOIN subjects sub ON comp.subject_id = sub.subject_id
        LEFT JOIN lessons l ON l.outcome_id = lo.outcome_id
        LEFT JOIN courses c ON l.course_id = c.course_id
        WHERE mr.learner_id = ?
        ORDER BY mr.updated_at DESC
    """, (learner_id,)).fetchall()

    concepts = conn.execute("""
        SELECT concept_tag, latest_score, concept_status, attempt_count
        FROM concept_mastery
        WHERE learner_id = ?
        ORDER BY latest_score ASC, attempt_count DESC
    """, (learner_id,)).fetchall()

    attempts = conn.execute("SELECT COUNT(*) AS total FROM assessment_attempts WHERE learner_id = ?", (learner_id,)).fetchone()["total"]
    logs = conn.execute("SELECT * FROM activity_logs WHERE learner_id = ? ORDER BY created_at DESC LIMIT 8", (learner_id,)).fetchall()

    avg_mastery = round(sum(r["mastery_score"] for r in records) / len(records), 1) if records else 0
    mastered = sum(1 for r in records if r["mastery_status"] == "Mastered")
    weak = [c for c in concepts if c["latest_score"] < 70]
    strong = [c for c in concepts if c["latest_score"] >= 70]

    if attempts <= 2:
        pace = "New learner"
    elif avg_mastery >= 85:
        pace = "Fast / High mastery"
    elif avg_mastery >= 65:
        pace = "Moderate"
    else:
        pace = "Needs guided support"

    summary = (
        f"This learner has completed {attempts} assessment attempt(s), mastered {mastered} outcome record(s), "
        f"and currently has an AI confidence average of {avg_mastery}%."
    )

    return {
        "user": user,
        "profile": profile,
        "records": records,
        "concepts": concepts,
        "weak_concepts": weak[:5],
        "strong_concepts": strong[:5],
        "attempts": attempts,
        "avg_mastery": avg_mastery,
        "mastered": mastered,
        "learning_pace": pace,
        "ai_summary": summary,
        "logs": logs,
    }


def refresh_learner_profile(conn, learner_id):
    records = conn.execute("""
        SELECT pretest_score, practice_score, posttest_score, mastery_score, mastery_status
        FROM mastery_records
        WHERE learner_id = ?
    """, (learner_id,)).fetchall()
    concepts = conn.execute("""
        SELECT concept_tag, latest_score, attempt_count
        FROM concept_mastery
        WHERE learner_id = ?
        ORDER BY latest_score ASC, attempt_count DESC
    """, (learner_id,)).fetchall()

    attempts = conn.execute(
        "SELECT COUNT(*) AS total FROM assessment_attempts WHERE learner_id = ?",
        (learner_id,),
    ).fetchone()["total"]

    avg_mastery = round(sum(r["mastery_score"] for r in records) / len(records), 1) if records else 0
    avg_pre = round(sum(r["pretest_score"] for r in records) / len(records), 1) if records else 0
    avg_post = round(sum(r["posttest_score"] for r in records) / len(records), 1) if records else 0
    learning_gain = max(0, round(avg_post - avg_pre, 1))
    weak = [c["concept_tag"] for c in concepts if c["latest_score"] < 70][:8]
    strong = [c["concept_tag"] for c in concepts if c["latest_score"] >= 70][:8]

    if attempts <= 2:
        pace = "New learner"
    elif avg_mastery >= 85:
        pace = "Fast / High mastery"
    elif avg_mastery >= 65:
        pace = "Moderate"
    else:
        pace = "Needs guided support"

    predicted = min(100, round((avg_mastery * 0.7) + (learning_gain * 0.3), 1))
    summary = (
        f"Attempts: {attempts}. Weak concepts: {', '.join(weak) or 'none currently'}. "
        f"Strong concepts: {', '.join(strong) or 'not enough evidence yet'}. "
        f"Predicted performance: {predicted}%."
    )

    conn.execute("""
        INSERT INTO learner_profiles
        (learner_id, learning_pace, preferred_support, ai_profile_summary,
         weak_concepts, strong_concepts, confidence_score, mastery_score,
         predicted_performance, learning_gain)
        VALUES (?, ?, 'Adaptive notes, video, worked examples and guided practice', ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(learner_id)
        DO UPDATE SET
            learning_pace=excluded.learning_pace,
            preferred_support=excluded.preferred_support,
            ai_profile_summary=excluded.ai_profile_summary,
            weak_concepts=excluded.weak_concepts,
            strong_concepts=excluded.strong_concepts,
            confidence_score=excluded.confidence_score,
            mastery_score=excluded.mastery_score,
            predicted_performance=excluded.predicted_performance,
            learning_gain=excluded.learning_gain,
            updated_at=CURRENT_TIMESTAMP
    """, (
        learner_id,
        pace,
        summary,
        ", ".join(weak),
        ", ".join(strong),
        avg_mastery,
        avg_mastery,
        predicted,
        learning_gain,
    ))
