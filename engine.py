def calculate_bkt(current_p, correct):
    """
    Simplified Bayesian Knowledge Tracing
    p(L_t) = p(L_{t-1} | Obs) + (1 - p(L_{t-1} | Obs)) * p(T)
    """
    # Parameters (standard defaults)
    p_transit = 0.1
    p_slip = 0.1
    p_guess = 0.2

    # Bayesian update (posterior)
    if correct:
        p_posterior = (current_p * (1 - p_slip)) / (current_p * (1 - p_slip) + (1 - current_p) * p_guess)
    else:
        p_posterior = (current_p * p_slip) / (current_p * p_slip + (1 - current_p) * (1 - p_guess))

    # Transition
    new_p = p_posterior + (1 - p_posterior) * p_transit

    # Clamp results to avoid certainty (0 or 1)
    return max(0.01, min(new_p, 0.99))

def get_recommendation(knowledge_level):
    if knowledge_level < 0.5:
        return "Review basic concepts and adaptive notes.", "Your mastery level is low, focus on understanding fundamentals."
    elif knowledge_level < 0.8:
        return "Complete adaptive practice questions.", "You are making progress. Practice will solidify your understanding."
    else:
        return "Submit practical evidence for mastery.", "You have high conceptual knowledge. Demonstrate it through practice."
