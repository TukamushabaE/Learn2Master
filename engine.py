import os
import json

def calculate_bkt(current_p, correct):
    """
    Bayesian Knowledge Tracing with Explainability
    Returns: (new_p, reasoning)
    """
    p_transit = float(os.environ.get('BKT_TRANSIT', 0.1))
    p_slip = float(os.environ.get('BKT_SLIP', 0.1))
    p_guess = float(os.environ.get('BKT_GUESS', 0.2))

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

class AIEngine:
    """
    Advanced AI Engine for Learn2Master.
    Future-ready for LLM and DKT integration.
    """
    @staticmethod
    def analyze_knowledge_gaps(mastery_records):
        """
        Identifies specific sub-competencies where the student is struggling.
        Returns a list of 'Gap' objects.
        """
        gaps = []
        for record in mastery_records:
            if record.knowledge_level < 0.5:
                gaps.append({
                    "lo_id": record.learning_outcome_id,
                    "name": record.learning_outcome.name,
                    "level": record.knowledge_level,
                    "priority": "High",
                    "reason": "Knowledge level is significantly below the threshold for competency."
                })
        return gaps

    @staticmethod
    def tutor_response(user_input, context):
        """
        Mock RAG-based LLM response.
        In production, this would call an LLM (e.g. GPT-4) with context injected.
        """
        username = context.get('username', 'Student')
        avg_mastery = context.get('avg_mastery', 0.0)
        recent_activity = context.get('recent_activity')
        gaps = context.get('gaps', [])

        user_input = user_input.lower()

        # Base Persona
        response = f"Hello {username}! I'm the Learn2Master AI Assistant, specialized in the Uganda CBC framework. "

        if "mastery" in user_input:
            msg = f"Your aggregate mastery is {avg_mastery:.1%}. "
            if avg_mastery > 0.8:
                msg += "Excellent work! You are nearing the 'Distinction' tier."
            else:
                msg += "You're making steady progress toward competency."
            return msg

        if "gap" in user_input or "struggle" in user_input or "help" in user_input:
            if gaps:
                gap = gaps[0]
                return f"I see you're currently challenged by '{gap['name']}' (Mastery: {gap['level']:.1%}). I suggest we revisit the 'Practical Examples' section for this topic."
            return "You don't have any major knowledge gaps right now. Great job! Ready to move to the next topic?"

        if "cbc" in user_input:
            return "The Competency-Based Curriculum (CBC) focuses on what you can *do*, not just what you know. My job is to help you bridge that gap through practical evidence and adaptive quizzes."

        # Default fallback
        return "I'm analyzing your progress. How can I assist you with your current Physics or ICT competencies today?"
