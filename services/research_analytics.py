"""Central, documented analytics for Learn2Master research evaluation."""

from statistics import mean, median, stdev, variance


def _number(value, digits=2):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0.0


def _filters(filters=None, alias="paired"):
    filters = filters or {}
    clauses = []
    params = []
    mapping = {
        "study_phase": f"{alias}.study_phase",
        "school_id": f"{alias}.school_id",
        "class_id": f"{alias}.class_id",
        "subject_id": f"{alias}.subject_id",
        "topic_id": f"{alias}.topic_id",
        "outcome_id": f"{alias}.outcome_id",
    }
    for key, column in mapping.items():
        value = filters.get(key)
        if value not in (None, ""):
            clauses.append(f"{column} = ?")
            params.append(value)
    if filters.get("date_from"):
        clauses.append(f"DATE({alias}.post_date) >= DATE(?)")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        clauses.append(f"DATE({alias}.post_date) <= DATE(?)")
        params.append(filters["date_to"])
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def paired_learning_gain_rows(conn, filters=None):
    """Pair the first pre-test with the first later post-test per participant/outcome.

    Pairing never crosses participant, learning outcome, subject, topic, or study
    phase boundaries. Scores in assessment_attempts are percentages.
    """
    where, params = _filters(filters)
    rows = conn.execute(f"""
        WITH eligible_attempts AS (
            SELECT aa.attempt_id, aa.learner_id, aa.assessment_id, aa.score,
                   aa.started_at, aa.completed_at, aa.time_spent_seconds,
                   aa.attempted_at, aa.weak_concepts,
                   a.assessment_type, a.total_marks,
                   l.outcome_id, lo.topic_id, lo.outcome_name,
                   c.subject_id, s.subject_name,
                   t.topic_title,
                   rp.id AS participant_id, rp.participant_code, rp.study_phase,
                   rp.school_id, rp.class_id,
                   schools.school_name, classes.class_name
            FROM assessment_attempts aa
            JOIN assessments a ON a.assessment_id=aa.assessment_id
            JOIN lessons l ON l.lesson_id=a.lesson_id
            JOIN learning_outcomes lo ON lo.outcome_id=l.outcome_id
            JOIN competencies c ON c.competency_id=lo.competency_id
            JOIN subjects s ON s.subject_id=c.subject_id
            LEFT JOIN topics t ON t.topic_id=lo.topic_id
            JOIN research_participants rp ON rp.user_id=aa.learner_id
                AND rp.active_status='Active'
                AND rp.consent_status='Granted'
                AND rp.assent_status IN ('Granted','Not Applicable')
                AND rp.parent_consent_status IN ('Granted','Not Applicable')
            LEFT JOIN schools ON schools.school_id=rp.school_id
            LEFT JOIN classes ON classes.class_id=rp.class_id
            WHERE a.assessment_type IN ('pretest','posttest')
        ),
        ranked_pre AS (
            SELECT ea.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY learner_id, outcome_id, study_phase
                       ORDER BY COALESCE(completed_at, attempted_at), attempt_id
                   ) AS pre_rank
            FROM eligible_attempts ea
            WHERE assessment_type='pretest'
        ),
        first_pre AS (
            SELECT * FROM ranked_pre WHERE pre_rank=1
        ),
        ranked_post AS (
            SELECT post.*,
                   pre.attempt_id AS pre_attempt_id,
                   pre.score AS pre_score,
                   pre.total_marks AS pre_total_marks,
                   pre.started_at AS pre_started_at,
                   COALESCE(pre.completed_at, pre.attempted_at) AS pre_date,
                   pre.weak_concepts AS pre_weak_concepts,
                   ROW_NUMBER() OVER (
                       PARTITION BY post.learner_id, post.outcome_id, post.study_phase
                       ORDER BY COALESCE(post.completed_at, post.attempted_at), post.attempt_id
                   ) AS post_rank
            FROM eligible_attempts post
            JOIN first_pre pre
              ON pre.learner_id=post.learner_id
             AND pre.outcome_id=post.outcome_id
             AND pre.study_phase=post.study_phase
             AND COALESCE(post.completed_at, post.attempted_at)
                 >= COALESCE(pre.completed_at, pre.attempted_at)
            WHERE post.assessment_type='posttest'
        ),
        paired AS (
            SELECT *,
                   COALESCE(completed_at, attempted_at) AS post_date
            FROM ranked_post
            WHERE post_rank=1
        )
        SELECT paired.*,
               mr.mastery_status, mr.mastery_score,
               (
                   SELECT COUNT(*) FROM assessment_attempts count_attempt
                   JOIN assessments count_assessment
                     ON count_assessment.assessment_id=count_attempt.assessment_id
                   JOIN lessons count_lesson ON count_lesson.lesson_id=count_assessment.lesson_id
                   WHERE count_attempt.learner_id=paired.learner_id
                     AND count_lesson.outcome_id=paired.outcome_id
                     AND COALESCE(count_attempt.completed_at, count_attempt.attempted_at)
                         BETWEEN paired.pre_date AND paired.post_date
               ) AS attempts,
               (
                   SELECT ROUND(CAST(AVG(ax.confidence_score) AS NUMERIC), 2)
                   FROM ai_explanations ax
                   WHERE ax.learner_id=paired.learner_id AND ax.outcome_id=paired.outcome_id
               ) AS ai_confidence,
               (
                   SELECT COUNT(*) FROM learning_reflections lr
                   WHERE lr.learner_id=paired.learner_id AND lr.outcome_id=paired.outcome_id
               ) AS reflection_count,
               (
                   SELECT COUNT(*) FROM practical_evidence pe
                   WHERE pe.learner_id=paired.learner_id AND pe.outcome_id=paired.outcome_id
               ) AS practical_count,
               (
                   SELECT COUNT(*) FROM teacher_interventions ti
                   WHERE ti.learner_id=paired.learner_id AND ti.outcome_id=paired.outcome_id
               ) AS teacher_intervention_count
        FROM paired
        LEFT JOIN mastery_records mr
          ON mr.learner_id=paired.learner_id AND mr.outcome_id=paired.outcome_id
        {where}
        ORDER BY paired.participant_code, paired.subject_name, paired.outcome_id
    """, params).fetchall()

    results = []
    for row in rows:
        pre = _number(row["pre_score"], 1)
        post = _number(row["score"], 1)
        gain = round(post - pre, 1)
        normalized_gain = round(gain / (100 - pre), 3) if pre < 100 else None
        percentage_improvement = round((gain / pre) * 100, 1) if pre > 0 else None
        results.append({
            "participant_code": row["participant_code"],
            "participant_id": row["participant_id"],
            "learner_id": row["learner_id"],
            "study_phase": row["study_phase"],
            "school_code": f"S{int(row['school_id']):03d}" if row["school_id"] else "",
            "school": row["school_name"] or "",
            "school_id": row["school_id"],
            "class": row["class_name"] or "",
            "class_id": row["class_id"],
            "subject": row["subject_name"],
            "subject_id": row["subject_id"],
            "topic": row["topic_title"] or "",
            "topic_id": row["topic_id"],
            "learning_outcome": row["outcome_name"],
            "outcome_id": row["outcome_id"],
            "pre_attempt_id": row["pre_attempt_id"],
            "post_attempt_id": row["attempt_id"],
            "pre_test": pre,
            "post_test": post,
            "absolute_gain": gain,
            "learning_gain": gain,
            "normalized_gain": normalized_gain if normalized_gain is not None else "Not applicable",
            "percentage_improvement": percentage_improvement if percentage_improvement is not None else "Not applicable",
            "pre_date": row["pre_date"],
            "post_date": row["post_date"],
            "mastery_status": row["mastery_status"] or "Not Started",
            "mastery_score": _number(row["mastery_score"], 1),
            "attempts": row["attempts"] or 0,
            "ai_confidence": _number(row["ai_confidence"], 1),
            "reflection_completed": "Yes" if row["reflection_count"] else "No",
            "practical_completed": "Yes" if row["practical_count"] else "No",
            "teacher_intervention": row["teacher_intervention_count"] or 0,
        })
    return results


def _sample_summary(values):
    values = [float(value) for value in values]
    if not values:
        return {"mean": 0, "median": 0, "sample_standard_deviation": 0, "sample_variance": 0}
    return {
        "mean": round(mean(values), 2),
        "median": round(median(values), 2),
        "sample_standard_deviation": round(stdev(values), 2) if len(values) > 1 else 0,
        "sample_variance": round(variance(values), 2) if len(values) > 1 else 0,
    }


def learning_gain_summary(rows):
    pre = [row["pre_test"] for row in rows]
    post = [row["post_test"] for row in rows]
    gains = [row["learning_gain"] for row in rows]
    normalized = [
        row["normalized_gain"]
        for row in rows
        if isinstance(row["normalized_gain"], (int, float))
    ]
    pre_stats = _sample_summary(pre)
    post_stats = _sample_summary(post)
    gain_stats = _sample_summary(gains)
    return {
        "valid_pairs": len(rows),
        "average_pre_test": pre_stats["mean"],
        "median_pre_test": pre_stats["median"],
        "pre_test_sample_standard_deviation": pre_stats["sample_standard_deviation"],
        "average_post_test": post_stats["mean"],
        "median_post_test": post_stats["median"],
        "post_test_sample_standard_deviation": post_stats["sample_standard_deviation"],
        "average_gain": gain_stats["mean"],
        "median_gain": gain_stats["median"],
        "gain_sample_standard_deviation": gain_stats["sample_standard_deviation"],
        "standard_deviation": gain_stats["sample_standard_deviation"],
        "variance": gain_stats["sample_variance"],
        "highest_gain": max(gains) if gains else 0,
        "lowest_gain": min(gains) if gains else 0,
        "positive_gain_count": sum(1 for gain in gains if gain > 0),
        "zero_gain_count": sum(1 for gain in gains if gain == 0),
        "negative_gain_count": sum(1 for gain in gains if gain < 0),
        "average_normalized_gain": round(mean(normalized), 3) if normalized else "Not applicable",
    }
