import os

filepath = 'app.py'
with open(filepath, 'r') as f:
    content = f.read()

search_text = """    new_level = calculate_bkt(mastery.knowledge_level, correct)
    rec, expl = get_recommendation(new_level)

    log = RecommendationLog(user_id=current_user.id, learning_outcome_id=lo_id, recommendation=rec, explanation=expl)
    db.session.add(log)

    mastery.knowledge_level = new_level"""

replace_text = """    p_before = mastery.knowledge_level
    new_level = calculate_bkt(p_before, correct)
    rec, expl = get_recommendation(new_level)

    log = RecommendationLog(user_id=current_user.id, learning_outcome_id=lo_id, recommendation=rec, explanation=expl)
    db.session.add(log)

    attempt = AttemptLog(
        user_id=current_user.id,
        learning_outcome_id=lo_id,
        correct=correct,
        p_before=p_before,
        p_after=new_level
    )
    db.session.add(attempt)

    mastery.knowledge_level = new_level"""

if "from models import db, User, Subject, Topic, LearningOutcome, MasteryRecord, Evidence, RecommendationLog" in content:
    content = content.replace(
        "from models import db, User, Subject, Topic, LearningOutcome, MasteryRecord, Evidence, RecommendationLog",
        "from models import db, User, Subject, Topic, LearningOutcome, MasteryRecord, Evidence, RecommendationLog, AttemptLog"
    )

if search_text in content:
    new_content = content.replace(search_text, replace_text)
    with open(filepath, 'w') as f:
        f.write(new_content)
    print("app.py updated for attempts.")
else:
    print("Search text not found.")
