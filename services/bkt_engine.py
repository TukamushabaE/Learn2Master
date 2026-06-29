"""Simplified Bayesian Knowledge Tracing engine for Learn2Master V8.
Transparent, explainable and suitable for dissertation demonstration.
"""


def update_bkt(p_mastery, correct, p_learn=0.12, p_slip=0.10, p_guess=0.20):
    p_mastery = max(0.0, min(1.0, float(p_mastery)))
    if correct:
        numerator = p_mastery * (1 - p_slip)
        denominator = numerator + (1 - p_mastery) * p_guess
    else:
        numerator = p_mastery * p_slip
        denominator = numerator + (1 - p_mastery) * (1 - p_guess)
    posterior = numerator / denominator if denominator else p_mastery
    return round(posterior + (1 - posterior) * p_learn, 4)


def concept_confidence(score, attempts=1):
    base = max(0, min(100, float(score))) / 100
    attempt_factor = min(1, attempts / 3)
    return round((base * 0.8 + attempt_factor * 0.2) * 100, 1)


def update_bkt_record(conn, learner_id, outcome_id, concept_tag, correct):
    row = conn.execute("""
        SELECT probability_mastery, observations, correct_attempts, incorrect_attempts,
               learn_probability, slip_probability, guess_probability
        FROM bkt_mastery
        WHERE learner_id=? AND outcome_id=? AND concept_tag=?
    """, (learner_id, outcome_id, concept_tag)).fetchone()
    current = row["probability_mastery"] if row else 0.20
    observations = row["observations"] if row else 0
    p_learn = row["learn_probability"] if row else 0.12
    p_slip = row["slip_probability"] if row else 0.10
    p_guess = row["guess_probability"] if row else 0.20
    updated = update_bkt(current, correct, p_learn=p_learn, p_slip=p_slip, p_guess=p_guess)
    next_observations = observations + 1
    next_correct = (row["correct_attempts"] if row else 0) + (1 if correct else 0)
    next_incorrect = (row["incorrect_attempts"] if row else 0) + (0 if correct else 1)
    confidence = concept_confidence(updated * 100, next_observations)
    learning_gain = round((updated - current) * 100, 1)
    predicted_mastery = round(updated * 100, 1)
    conn.execute("""
        INSERT INTO bkt_mastery
        (learner_id, outcome_id, concept_tag, prior_mastery_probability, learn_probability,
         guess_probability, slip_probability, probability_mastery, current_mastery_probability,
         confidence_score, confidence, observations, attempts, correct_attempts, incorrect_attempts,
         learning_gain, time_spent_minutes, predicted_mastery, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, 2, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(learner_id, outcome_id, concept_tag)
        DO UPDATE SET
            probability_mastery=excluded.probability_mastery,
            current_mastery_probability=excluded.current_mastery_probability,
            confidence_score=excluded.confidence_score,
            confidence=excluded.confidence,
            observations=bkt_mastery.observations + 1,
            attempts=bkt_mastery.attempts + 1,
            correct_attempts=excluded.correct_attempts,
            incorrect_attempts=excluded.incorrect_attempts,
            learning_gain=excluded.learning_gain,
            time_spent_minutes=bkt_mastery.time_spent_minutes + 2,
            predicted_mastery=excluded.predicted_mastery,
            last_updated=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP
    """, (
        learner_id, outcome_id, concept_tag, current, p_learn, p_guess, p_slip, updated,
        updated, confidence, confidence, next_correct, next_incorrect, learning_gain,
        predicted_mastery,
    ))
    return updated, next_observations


def bkt_summary(conn, learner_id, outcome_id):
    rows = conn.execute("""
        SELECT concept_tag, probability_mastery, current_mastery_probability, confidence_score,
               confidence, observations, attempts, correct_attempts, incorrect_attempts,
               learning_gain, time_spent_minutes, predicted_mastery
        FROM bkt_mastery
        WHERE learner_id=? AND outcome_id=?
        ORDER BY concept_tag
    """, (learner_id, outcome_id)).fetchall()
    return rows
