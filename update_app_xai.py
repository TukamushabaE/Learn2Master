import os

filepath = 'app.py'
with open(filepath, 'r') as f:
    content = f.read()

search_text = """    p_before = mastery.knowledge_level
    new_level = calculate_bkt(p_before, correct)
    rec, expl = get_recommendation(new_level)

    log = RecommendationLog(user_id=current_user.id, learning_outcome_id=lo_id, recommendation=rec, explanation=expl)
    db.session.add(log)"""

replace_text = """    p_before = mastery.knowledge_level
    new_level, reasoning = calculate_bkt(p_before, correct)
    rec, expl = get_recommendation(new_level)

    # Enrich explanation with AI reasoning for XAI
    full_explanation = f"{expl} | AI Insight: {reasoning['message']}"

    log = RecommendationLog(user_id=current_user.id, learning_outcome_id=lo_id, recommendation=rec, explanation=full_explanation)
    db.session.add(log)"""

if search_text in content:
    new_content = content.replace(search_text, replace_text)
    with open(filepath, 'w') as f:
        f.write(new_content)
    print("app.py updated for XAI.")
else:
    print("Search text not found.")
