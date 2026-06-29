"""Explainable recommendation engine for Learn2Master."""


def build_recommendation(outcome_name, assessment_type, score, weak_concepts, mastery_score=None):
    weak = ", ".join(weak_concepts) if weak_concepts else "no major weak concept detected"
    strong_concepts = []
    confidence = mastery_score if mastery_score is not None else score
    expected_mastery = min(100, max(score, confidence) + (10 if weak_concepts else 5))
    estimated_study_minutes = 25 if weak_concepts else 10
    recommended_resource = "adaptive notes, worked examples, video support and concept practice"
    evidence_used = (
        f"{assessment_type.title()} score {score}%; weak concept evidence: {weak}; "
        f"algorithm confidence {confidence}%."
    )

    if assessment_type == "pretest":
        return {
            "type": "Adaptive Learning Path",
            "reason": (
                f"Pre-test diagnostic for '{outcome_name}' scored {score}%. "
                f"Weak concept(s): {weak}. The system has selected adaptive notes, videos, "
                "and practice questions before the post-test."
            ),
            "evidence_used": evidence_used,
            "weak_concepts": weak,
            "strong_concepts": ", ".join(strong_concepts),
            "confidence_score": confidence,
            "expected_mastery": expected_mastery,
            "estimated_study_minutes": estimated_study_minutes,
            "recommended_resource": recommended_resource,
        }

    if assessment_type == "practice":
        return {
            "type": "Practice Support",
            "reason": (
                f"Practice score for '{outcome_name}' is {score}%. Weak concept(s): {weak}. "
                "Revise the adaptive notes and attempt the practice again before the post-test."
            ),
            "evidence_used": evidence_used,
            "weak_concepts": weak,
            "strong_concepts": ", ".join(strong_concepts),
            "confidence_score": confidence,
            "expected_mastery": expected_mastery,
            "estimated_study_minutes": estimated_study_minutes,
            "recommended_resource": recommended_resource,
        }

    if mastery_score is not None and mastery_score >= 80:
        return {
            "type": "Unlock Next Outcome",
            "reason": (
                f"Post-test score is {score}% and algorithm mastery is {mastery_score}%. "
                "Mastery has been attained, so the next learning outcome is unlocked."
            ),
            "evidence_used": evidence_used,
            "weak_concepts": weak,
            "strong_concepts": ", ".join(strong_concepts),
            "confidence_score": confidence,
            "expected_mastery": 100,
            "estimated_study_minutes": 0,
            "recommended_resource": "next unlocked learning outcome",
        }

    return {
        "type": "Remediation Required",
        "reason": (
            f"Post-test score is {score}% and algorithm mastery is {mastery_score}%. "
            f"Weak concept(s): {weak}. The next learning outcome remains locked. "
            "Review the recommended notes, watch the video, and redo practice before attempting the post-test again."
        ),
        "evidence_used": evidence_used,
        "weak_concepts": weak,
        "strong_concepts": ", ".join(strong_concepts),
        "confidence_score": confidence,
        "expected_mastery": expected_mastery,
        "estimated_study_minutes": estimated_study_minutes,
        "recommended_resource": recommended_resource,
    }
