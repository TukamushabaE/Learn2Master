
def has_reflection(conn, learner_id, outcome_id):
    row = conn.execute("""
        SELECT reflection_id FROM learning_reflections
        WHERE learner_id = ? AND outcome_id = ?
        ORDER BY created_at DESC LIMIT 1
    """, (learner_id, outcome_id)).fetchone()
    return bool(row)


def latest_reflection(conn, learner_id, outcome_id):
    return conn.execute("""
        SELECT * FROM learning_reflections
        WHERE learner_id = ? AND outcome_id = ?
        ORDER BY created_at DESC LIMIT 1
    """, (learner_id, outcome_id)).fetchone()


def evidence_checklist(pretest_attempt, practice_attempt, posttest_attempt, weak_resolved, reflection_done, posttest_score, threshold, practical_done=True):
    return {
        "pretest_completed": bool(pretest_attempt),
        "adaptive_practice_completed": bool(practice_attempt),
        "weak_concepts_resolved": bool(weak_resolved),
        "reflection_completed": bool(reflection_done),
        "practical_evidence_completed": bool(practical_done),
        "posttest_completed": bool(posttest_attempt),
        "posttest_passed": bool(posttest_attempt and posttest_score >= threshold),
    }


def record_ai_explanation(conn, learner_id, outcome_id, decision_type, evidence_used, explanation_text, confidence_score):
    conn.execute("""
        INSERT INTO ai_explanations
        (learner_id, outcome_id, decision_type, evidence_used, explanation_text, confidence_score)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (learner_id, outcome_id, decision_type, evidence_used, explanation_text, confidence_score))
