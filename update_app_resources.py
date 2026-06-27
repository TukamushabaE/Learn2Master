import os

filepath = 'app.py'
with open(filepath, 'r') as f:
    content = f.read()

if "Evidence, RecommendationLog, AttemptLog" in content:
    content = content.replace(
        "Evidence, RecommendationLog, AttemptLog",
        "Evidence, RecommendationLog, AttemptLog, LearningResource"
    )

search_text = """    mastery = MasteryRecord.query.filter_by(user_id=current_user.id, learning_outcome_id=lo_id).first()
    knowledge_level = mastery.knowledge_level if mastery else 0.0
    rec, expl = get_recommendation(knowledge_level)
    return render_template('learning_outcome.html', lo=lo, knowledge_level=knowledge_level, recommendation=rec, explanation=expl, is_locked=is_locked)"""

replace_text = """    mastery = MasteryRecord.query.filter_by(user_id=current_user.id, learning_outcome_id=lo_id).first()
    knowledge_level = mastery.knowledge_level if mastery else 0.0

    # Adaptive resource selection
    resources = LearningResource.query.filter(
        LearningResource.learning_outcome_id == lo_id,
        LearningResource.min_mastery <= knowledge_level,
        LearningResource.max_mastery >= knowledge_level
    ).all()

    rec, expl = get_recommendation(knowledge_level)
    return render_template('learning_outcome.html', lo=lo, knowledge_level=knowledge_level, recommendation=rec, explanation=expl, is_locked=is_locked, resources=resources)"""

if search_text in content:
    new_content = content.replace(search_text, replace_text)
    with open(filepath, 'w') as f:
        f.write(new_content)
    print("app.py updated for Adaptive Resources.")
else:
    print("Search text not found.")
