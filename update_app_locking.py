import os

filepath = 'app.py'
with open(filepath, 'r') as f:
    content = f.read()

search_text = """@app.route('/learning_outcome/<int:lo_id>')
@login_required
@role_required('student', 'teacher', 'admin')
def view_lo(lo_id):
    lo = LearningOutcome.query.get_or_404(lo_id)
    mastery = MasteryRecord.query.filter_by(user_id=current_user.id, learning_outcome_id=lo_id).first()
    knowledge_level = mastery.knowledge_level if mastery else 0.0
    rec, expl = get_recommendation(knowledge_level)
    return render_template('learning_outcome.html', lo=lo, knowledge_level=knowledge_level, recommendation=rec, explanation=expl)"""

replace_text = """@app.route('/learning_outcome/<int:lo_id>')
@login_required
@role_required('student', 'teacher', 'admin')
def view_lo(lo_id):
    lo = LearningOutcome.query.get_or_404(lo_id)

    # Check for sequential locking (only for students)
    is_locked = False
    if current_user.role == 'student':
        previous_los = LearningOutcome.query.filter(
            LearningOutcome.topic_id == lo.topic_id,
            LearningOutcome.order < lo.order
        ).all()

        for prev_lo in previous_los:
            prev_mastery = MasteryRecord.query.filter_by(
                user_id=current_user.id,
                learning_outcome_id=prev_lo.id
            ).first()
            if not prev_mastery or prev_mastery.knowledge_level < 0.85:
                is_locked = True
                break

    mastery = MasteryRecord.query.filter_by(user_id=current_user.id, learning_outcome_id=lo_id).first()
    knowledge_level = mastery.knowledge_level if mastery else 0.0
    rec, expl = get_recommendation(knowledge_level)
    return render_template('learning_outcome.html', lo=lo, knowledge_level=knowledge_level, recommendation=rec, explanation=expl, is_locked=is_locked)"""

if search_text in content:
    new_content = content.replace(search_text, replace_text)
    with open(filepath, 'w') as f:
        f.write(new_content)
    print("app.py updated successfully.")
else:
    print("Search text not found.")
