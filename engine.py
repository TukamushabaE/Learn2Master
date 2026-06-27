def calculate_bkt(current_p, correct):
    """
    Bayesian Knowledge Tracing with Explainability
    Returns: (new_p, reasoning)
    """
    p_transit = 0.1
    p_slip = 0.1
    p_guess = 0.2

    if correct:
        p_posterior = (current_p * (1 - p_slip)) / (current_p * (1 - p_slip) + (1 - current_p) * p_guess)
        explanation = f"Correct answer detected. Probability of mastery increased from {current_p:.2f} to {p_posterior:.2f} before transition."
    else:
        p_posterior = (current_p * p_slip) / (current_p * p_slip + (1 - current_p) * (1 - p_guess))
        explanation = f"Incorrect answer detected. Mastery lowered to {p_posterior:.2f}. Suggests potential slip or knowledge gap."

    new_p = p_posterior + (1 - p_posterior) * p_transit
    new_p = max(0.01, min(new_p, 0.99))

    reasoning = {
        "p_before": current_p,
        "p_after": new_p,
        "change": new_p - current_p,
        "message": explanation,
        "parameters": {"slip": p_slip, "guess": p_guess, "transit": p_transit}
    }

    return new_p, reasoning

def get_recommendation(knowledge_level):
    if knowledge_level < 0.5:
        return "Review basic concepts and adaptive notes.", "Your current knowledge level (pL) is below 0.5, requiring foundational reinforcement."
    elif knowledge_level < 0.85:
        return "Complete adaptive practice questions.", "You are in the zone of proximal development (0.5 < pL < 0.85). Practice will solidify your mental models."
    else:
        return "Submit practical evidence for mastery.", "High conceptual mastery detected (pL >= 0.85). Demonstrate competency through practical application."
