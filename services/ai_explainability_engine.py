
def build_ai_explanation(outcome_name, assessment_type, score, weak_concepts, evidence, final_status=None):
    weak = ", ".join(c.replace("_", " ").title() for c in weak_concepts) if weak_concepts else "No major weak concept detected"
    evidence_text = []
    for key, value in (evidence or {}).items():
        evidence_text.append(f"{key.replace('_', ' ').title()}: {'Yes' if value else 'No'}")

    if assessment_type == "pretest":
        decision = "Diagnostic Adaptive Path"
        explanation = (
            f"The pre-test for '{outcome_name}' scored {score}%. The system identified: {weak}. "
            "It therefore recommends adaptive notes, videos and concept-targeted practice before post-test."
        )
    elif assessment_type == "practice":
        decision = "Practice Mastery Check"
        explanation = (
            f"Practice score for '{outcome_name}' is {score}%. Current weak concept focus: {weak}. "
            "Post-test remains locked until required practice, reflection and weak-concept evidence are complete."
        )
    else:
        decision = "Evidence-Based Mastery Decision"
        explanation = (
            f"Post-test score for '{outcome_name}' is {score}%. Final status: {final_status}. "
            f"Evidence reviewed: {'; '.join(evidence_text)}."
        )

    return {"decision": decision, "explanation": explanation, "evidence_used": "; ".join(evidence_text)}
