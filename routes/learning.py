from collections import defaultdict

from flask import Blueprint, render_template, request, redirect, session, url_for, flash
import os
import uuid
from werkzeug.utils import secure_filename

from routes.guards import role_required
from database import get_db
from security import csrf_protect
from services.mastery_engine import calculate_percentage, calculate_mastery, mastery_status, mastery_level, evidence_based_mastery
from services.recommendation_engine import build_recommendation
from services.evidence_engine import has_reflection, latest_reflection, evidence_checklist, record_ai_explanation
from services.ai_explainability_engine import build_ai_explanation
from services.bkt_engine import update_bkt_record, bkt_summary
from services.learner_profile_engine import refresh_learner_profile
from services.offline_engine import queue_offline_event

learning_bp = Blueprint("learning", __name__)

PRACTICE_CONCEPT_THRESHOLD = 70
EVIDENCE_TYPE_LABELS = {
    "activity": "Activity Evidence",
    "project": "Project Evidence",
    "investigation": "Investigation Evidence",
    "practical": "Practical Evidence",
    "reflection": "Reflection Evidence",
}
ACTIVITY_GUIDANCE = {
    "project": {
        "learning": "Create a product, report, model, program, poster, table, or solution that applies the concept to a real need.",
        "evidence": "Upload the finished product, photo, screenshot, code file, report, or a short explanation of what you created.",
    },
    "investigation": {
        "learning": "Ask a focused question, collect evidence, compare results, and explain what the evidence shows.",
        "evidence": "Submit your investigation notes, data table, photo, graph, or written conclusion.",
    },
    "practical": {
        "learning": "Carry out the hands-on task carefully, observe what happens, and record measurements or outputs.",
        "evidence": "Upload a photo, lab report, screenshot, code file, measurement table, or signed observation note.",
    },
    "simulation": {
        "learning": "Use the diagram, model, or simulation to test the idea and observe patterns before explaining them.",
        "evidence": "Submit a screenshot, labelled diagram, result table, or explanation of what changed and why.",
    },
    "collaboration": {
        "learning": "Work with a peer or group to compare ideas, agree on evidence, and communicate a justified answer.",
        "evidence": "Submit group notes, peer feedback, a discussion summary, or the agreed solution.",
    },
    "communication": {
        "learning": "Explain the concept clearly using examples, diagrams, demonstrations, or presentation notes.",
        "evidence": "Submit slides, a photo of your explanation, notes, or a short written summary.",
    },
    "reflection": {
        "learning": "Think about what was difficult, what helped, and how you can apply the concept in real life.",
        "evidence": "Write your reflection and confidence level.",
    },
}
POSTTEST_SYSTEM_BLOCKERS = {
    "pretest_required": {
        "title": "Pre-test Required",
        "detail": "Complete the diagnostic pre-test before the post-test can open.",
    },
    "practice_not_available": {
        "title": "Practice Not Available",
        "detail": "The teacher or administrator needs to add adaptive practice for this outcome.",
    },
    "practice_required": {
        "title": "Adaptive Practice Required",
        "detail": f"Score at least {PRACTICE_CONCEPT_THRESHOLD}% in adaptive practice.",
    },
    "reflection_required": {
        "title": "Reflection Required",
        "detail": "Submit the learner reflection for this outcome.",
    },
    "practical_evidence_required": {
        "title": "Practical Evidence Required",
        "detail": "Upload practical or project evidence for this outcome.",
    },
}


def concept_label(concept):
    return str(concept or "").replace("_", " ").title()


def split_posttest_blockers(blockers):
    system_blockers = []
    concept_blockers = []
    for blocker in blockers or []:
        if blocker in POSTTEST_SYSTEM_BLOCKERS:
            system_blockers.append(blocker)
        else:
            concept_blockers.append(blocker)
    return system_blockers, concept_blockers


def describe_posttest_blockers(blockers):
    system_blockers, concept_blockers = split_posttest_blockers(blockers)
    descriptions = []
    if concept_blockers:
        descriptions.append({
            "kind": "concept",
            "title": "Weak Concept Practice",
            "detail": (
                f"Reach {PRACTICE_CONCEPT_THRESHOLD}% or above in: "
                + ", ".join(concept_label(concept) for concept in concept_blockers)
                + "."
            ),
        })
    for blocker in system_blockers:
        item = POSTTEST_SYSTEM_BLOCKERS[blocker]
        descriptions.append({
            "kind": "evidence",
            "title": item["title"],
            "detail": item["detail"],
        })
    return descriptions


def posttest_blocker_summary(blockers):
    descriptions = describe_posttest_blockers(blockers)
    if not descriptions:
        return "Complete the required learning evidence first."
    return " ".join(item["detail"] for item in descriptions)


def allowed_upload(filename):
    if not filename or "." not in filename:
        return False
    extension = os.path.splitext(filename)[1].lower()
    from flask import current_app
    return extension in current_app.config["UPLOAD_EXTENSIONS"]


def guidance_for_activity(activity_type):
    normalized = (activity_type or "").strip().lower()
    for key, value in ACTIVITY_GUIDANCE.items():
        if key in normalized:
            return value
    return {
        "learning": "Complete the task by applying the concept to a real classroom, home, community, or school situation.",
        "evidence": "Submit a short explanation, file, photo, screenshot, report, table, code, or other proof of what you completed.",
    }


def save_evidence_file(file, learner_id, outcome_id):
    if not file or not file.filename:
        return None, None, 0, None
    if not allowed_upload(file.filename):
        return None, None, 0, "Unsupported evidence file type. Please upload a PDF, image, text, Word, Python, or ZIP file."

    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "learner_evidence")
    os.makedirs(upload_dir, exist_ok=True)
    original_name = secure_filename(file.filename)
    filename = secure_filename(f"learner_{learner_id}_outcome_{outcome_id}_{uuid.uuid4().hex}_{original_name}")
    absolute_path = os.path.join(upload_dir, filename)
    file.save(absolute_path)
    file_path = os.path.join("uploads", "learner_evidence", filename)
    return file_path, os.path.splitext(filename)[1].lower(), os.path.getsize(absolute_path), None


def outcome_meta(conn, outcome_id):
    return conn.execute("""
        SELECT lo.outcome_id, lo.topic_id, lo.competency_id, c.subject_id
        FROM learning_outcomes lo
        JOIN competencies c ON c.competency_id=lo.competency_id
        WHERE lo.outcome_id=?
    """, (outcome_id,)).fetchone()


def evidence_progress(conn, learner_id, outcome_id, practical_required=False):
    total_activities = conn.execute("""
        SELECT COUNT(*) AS total
        FROM learning_activities
        WHERE outcome_id=? AND evidence_required=1
    """, (outcome_id,)).fetchone()["total"]
    completed_activities = conn.execute("""
        SELECT COUNT(DISTINCT activity_id) AS total
        FROM activity_submissions
        WHERE learner_id=? AND outcome_id=?
    """, (learner_id, outcome_id)).fetchone()["total"]
    reflection_done = 1 if has_reflection(conn, learner_id, outcome_id) else 0
    practical_done = 1 if practical_evidence_done(conn, learner_id, outcome_id) else 0

    total_required = total_activities + 1 + (1 if practical_required else 0)
    completed = min(completed_activities, total_activities) + reflection_done + (practical_done if practical_required else 0)
    percentage = round((completed / total_required) * 100) if total_required else 0
    return {
        "total_required": total_required,
        "completed": completed,
        "percentage": min(100, percentage),
        "activity_total": total_activities,
        "activity_completed": min(completed_activities, total_activities),
        "reflection_done": bool(reflection_done),
        "practical_required": bool(practical_required),
        "practical_done": bool(practical_done) if practical_required else True,
    }


def activity_submission_map(conn, learner_id, outcome_id):
    rows = conn.execute("""
        SELECT activity_id, COUNT(*) AS submission_count, MAX(created_at) AS latest_submission
        FROM activity_submissions
        WHERE learner_id=? AND outcome_id=?
        GROUP BY activity_id
    """, (learner_id, outcome_id)).fetchall()
    return {row["activity_id"]: row for row in rows}


def get_latest_attempt(conn, learner_id, assessment_id):
    return conn.execute("""
        SELECT * FROM assessment_attempts
        WHERE learner_id = ? AND assessment_id = ?
        ORDER BY attempted_at DESC, attempt_id DESC
        LIMIT 1
    """, (learner_id, assessment_id)).fetchone()


def get_assessment(conn, lesson_id, assessment_type):
    return conn.execute("""
        SELECT * FROM assessments
        WHERE lesson_id = ? AND assessment_type = ?
        LIMIT 1
    """, (lesson_id, assessment_type)).fetchone()


def is_outcome_unlocked(conn, learner_id, outcome):
    if outcome["sequence_order"] == 1:
        return True

    previous = conn.execute("""
        SELECT prev.outcome_id
        FROM learning_outcomes current
        JOIN learning_outcomes prev
            ON prev.competency_id = current.competency_id
           AND prev.sequence_order = current.sequence_order - 1
        WHERE current.outcome_id = ?
    """, (outcome["outcome_id"],)).fetchone()

    if not previous:
        return True

    previous_mastery = conn.execute("""
        SELECT mastery_status
        FROM mastery_records
        WHERE learner_id = ? AND outcome_id = ?
    """, (learner_id, previous["outcome_id"])).fetchone()

    return bool(previous_mastery and previous_mastery["mastery_status"] == "Mastered")


def get_required_concepts(conn, outcome_id):
    rows = conn.execute("""
        SELECT DISTINCT concept_tag
        FROM adaptive_notes
        WHERE outcome_id = ?
        ORDER BY priority, concept_tag
    """, (outcome_id,)).fetchall()
    return [row["concept_tag"] for row in rows]


def get_concept_mastery(conn, learner_id, outcome_id):
    rows = conn.execute("""
        SELECT concept_tag, latest_score, latest_assessment_type, attempt_count, concept_status
        FROM concept_mastery
        WHERE learner_id = ? AND outcome_id = ?
        ORDER BY concept_tag
    """, (learner_id, outcome_id)).fetchall()
    return {row["concept_tag"]: row for row in rows}


def get_latest_weak_concepts(conn, learner_id, outcome_id, pretest_attempt, required_concepts):
    concept_map = get_concept_mastery(conn, learner_id, outcome_id)

    practice_weak = [
        concept for concept in required_concepts
        if concept in concept_map
        and concept_map[concept]["latest_assessment_type"] == "practice"
        and concept_map[concept]["latest_score"] < PRACTICE_CONCEPT_THRESHOLD
    ]
    if practice_weak:
        return practice_weak

    never_practiced = [
        concept for concept in required_concepts
        if concept not in concept_map or concept_map[concept]["latest_assessment_type"] != "practice"
    ]
    if never_practiced and pretest_attempt:
        if pretest_attempt["weak_concepts"]:
            pre_weak = [c.strip() for c in pretest_attempt["weak_concepts"].split(",") if c.strip()]
            return pre_weak or never_practiced
        return never_practiced

    return required_concepts


def get_pretest_weak_concepts(conn, learner_id, outcome_id):
    pretest = conn.execute("""
        SELECT a.assessment_id
        FROM assessments a
        JOIN lessons l ON a.lesson_id = l.lesson_id
        WHERE l.outcome_id = ? AND a.assessment_type = 'pretest'
        LIMIT 1
    """, (outcome_id,)).fetchone()

    if not pretest:
        return None, ["pretest_not_available"]

    attempt = get_latest_attempt(conn, learner_id, pretest["assessment_id"])
    if not attempt:
        return None, ["pretest_required"]

    weak = [
        c.strip()
        for c in (attempt["weak_concepts"] or "").split(",")
        if c.strip()
    ]
    return attempt, weak


def posttest_unlock_status(conn, learner_id, outcome_id, required_concepts):
    """Unlock post-test only after learning/practice evidence exists.

    Rule:
    1. Pre-test must be attempted.
    2. Practice must be attempted and reach the concept threshold.
    3. If pre-test identified weak concepts, each weak concept must be mastered in practice.
       If pre-test had no weak concepts, one general practice attempt of 70%+ is still required.
    """
    pretest_attempt, weak_concepts = get_pretest_weak_concepts(conn, learner_id, outcome_id)
    if pretest_attempt is None:
        return False, weak_concepts
    outcome_row = conn.execute("""
        SELECT practical_required FROM learning_outcomes WHERE outcome_id=?
    """, (outcome_id,)).fetchone()

    practice = conn.execute("""
        SELECT a.assessment_id
        FROM assessments a
        JOIN lessons l ON a.lesson_id = l.lesson_id
        WHERE l.outcome_id = ? AND a.assessment_type = 'practice'
        LIMIT 1
    """, (outcome_id,)).fetchone()

    if not practice:
        return False, ["practice_not_available"]

    practice_attempt = get_latest_attempt(conn, learner_id, practice["assessment_id"])
    if not practice_attempt:
        return False, ["practice_required"]

    if not weak_concepts:
        if practice_attempt["score"] < PRACTICE_CONCEPT_THRESHOLD:
            return False, ["practice_required"]
        if not has_reflection(conn, learner_id, outcome_id):
            return False, ["reflection_required"]
        if outcome_row and outcome_row["practical_required"] and not practical_evidence_done(conn, learner_id, outcome_id):
            return False, ["practical_evidence_required"]
        return True, []

    concept_map = get_concept_mastery(conn, learner_id, outcome_id)
    not_ready = []

    for concept in weak_concepts:
        row = concept_map.get(concept)
        if not row:
            not_ready.append(concept)
            continue
        if row["latest_assessment_type"] in ["practice", "posttest"] and row["latest_score"] >= PRACTICE_CONCEPT_THRESHOLD:
            continue
        not_ready.append(concept)

    if len(not_ready) == 0 and not has_reflection(conn, learner_id, outcome_id):
        return False, ["reflection_required"]
    if len(not_ready) == 0 and outcome_row and outcome_row["practical_required"] and not practical_evidence_done(conn, learner_id, outcome_id):
        return False, ["practical_evidence_required"]

    return len(not_ready) == 0, not_ready


def weak_concepts_resolved(conn, learner_id, outcome_id):
    pretest_attempt, weak_concepts = get_pretest_weak_concepts(conn, learner_id, outcome_id)
    if pretest_attempt is None:
        return False

    practice = conn.execute("""
        SELECT a.assessment_id
        FROM assessments a
        JOIN lessons l ON a.lesson_id = l.lesson_id
        WHERE l.outcome_id = ? AND a.assessment_type = 'practice'
        LIMIT 1
    """, (outcome_id,)).fetchone()
    if not practice:
        return False

    practice_attempt = get_latest_attempt(conn, learner_id, practice["assessment_id"])
    if not practice_attempt:
        return False

    if not weak_concepts:
        return practice_attempt["score"] >= PRACTICE_CONCEPT_THRESHOLD

    concept_map = get_concept_mastery(conn, learner_id, outcome_id)
    for concept in weak_concepts:
        row = concept_map.get(concept)
        if not row:
            return False
        if row["latest_assessment_type"] not in ["practice", "posttest"]:
            return False
        if row["latest_score"] < PRACTICE_CONCEPT_THRESHOLD:
            return False
    return True


def latest_practical_evidence(conn, learner_id, outcome_id):
    return conn.execute("""
        SELECT * FROM practical_evidence
        WHERE learner_id=? AND outcome_id=?
        ORDER BY created_at DESC LIMIT 1
    """, (learner_id, outcome_id)).fetchone()


def practical_evidence_done(conn, learner_id, outcome_id):
    return bool(latest_practical_evidence(conn, learner_id, outcome_id))


def prepare_question_items(conn, assessment_id, concept_tags=None, limit=6, learner_id=None):
    params = [assessment_id]
    concept_filter = ""

    if concept_tags:
        placeholders = ",".join("?" for _ in concept_tags)
        concept_filter = f" AND q.concept_tag IN ({placeholders})"
        params.extend(concept_tags)

    exclude_filter = ""
    if learner_id:
        exclude_filter = """
        AND q.question_id NOT IN (
            SELECT aa.question_id
            FROM attempt_answers aa
            JOIN assessment_attempts at ON aa.attempt_id = at.attempt_id
            WHERE at.learner_id = ?
              AND at.assessment_id = ?
        )
        """
        params.extend([learner_id, assessment_id])

    questions = conn.execute(f"""
        SELECT q.question_id, q.question_text, q.concept_tag, q.question_type,
               q.correct_answer, q.marks, q.bloom_level, q.difficulty_level
        FROM questions q
        WHERE q.assessment_id = ?
        {concept_filter}
        {exclude_filter}
        ORDER BY RANDOM()
        LIMIT ?
    """, (*params, limit)).fetchall()

    # If the learner has exhausted fresh questions, reuse the bank but randomize again.
    if not questions:
        params = [assessment_id]
        concept_filter = ""
        if concept_tags:
            placeholders = ",".join("?" for _ in concept_tags)
            concept_filter = f" AND concept_tag IN ({placeholders})"
            params.extend(concept_tags)

        questions = conn.execute(f"""
            SELECT question_id, question_text, concept_tag, question_type,
                   correct_answer, marks, bloom_level, difficulty_level
            FROM questions
            WHERE assessment_id = ?
            {concept_filter}
            ORDER BY RANDOM()
            LIMIT ?
        """, (*params, limit)).fetchall()

    question_items = []
    for q in questions:
        options = conn.execute("""
            SELECT option_id, option_text
            FROM question_options
            WHERE question_id = ?
            ORDER BY RANDOM()
        """, (q["question_id"],)).fetchall()
        question_items.append({"question": q, "options": options})
    return question_items


def update_concept_mastery(conn, learner_id, outcome_id, assessment_type, concept_stats):
    for concept, stats in concept_stats.items():
        total = stats["total"]
        correct = stats["correct"]
        score = calculate_percentage(correct, total)

        if assessment_type == "pretest":
            status = "Diagnostic Strong" if score >= PRACTICE_CONCEPT_THRESHOLD else "Diagnostic Weak"
        elif assessment_type == "practice":
            status = "Concept Mastered" if score >= PRACTICE_CONCEPT_THRESHOLD else "More Practice Needed"
        elif assessment_type == "posttest":
            status = "Post-test Strong" if score >= PRACTICE_CONCEPT_THRESHOLD else "Post-test Weak"
        else:
            status = "Attempted"

        conn.execute("""
            INSERT INTO concept_mastery
            (learner_id, outcome_id, concept_tag, latest_score, latest_assessment_type, attempt_count, concept_status)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(learner_id, outcome_id, concept_tag)
            DO UPDATE SET
                latest_score = excluded.latest_score,
                latest_assessment_type = excluded.latest_assessment_type,
                attempt_count = concept_mastery.attempt_count + 1,
                concept_status = excluded.concept_status,
                updated_at = CURRENT_TIMESTAMP
        """, (learner_id, outcome_id, concept, score, assessment_type, status))


@learning_bp.route("/pathway/<int:course_id>")
@role_required("learner")
def pathway(course_id):
    learner_id = session["user_id"]
    conn = get_db()

    course = conn.execute("""
        SELECT courses.*, subjects.subject_name
        FROM courses
        JOIN subjects ON courses.subject_id = subjects.subject_id
        WHERE courses.course_id = ?
    """, (course_id,)).fetchone()

    if not course:
        conn.close()
        return "Pathway not found", 404

    outcomes = conn.execute("""
        SELECT
            lo.outcome_id, lo.outcome_code, lo.outcome_name, lo.outcome_description,
            lo.mastery_threshold, lo.sequence_order, lessons.lesson_id, lessons.lesson_title,
            COALESCE(mr.mastery_score, 0) AS mastery_score,
            COALESCE(mr.mastery_status, 'Not Started') AS mastery_status,
            COALESCE(mr.pretest_score, 0) AS pretest_score,
            COALESCE(mr.practice_score, 0) AS practice_score,
            COALESCE(mr.posttest_score, 0) AS posttest_score
        FROM learning_outcomes lo
        JOIN lessons ON lessons.outcome_id = lo.outcome_id
        LEFT JOIN mastery_records mr
            ON mr.outcome_id = lo.outcome_id AND mr.learner_id = ?
        WHERE lessons.course_id = ?
        ORDER BY lo.sequence_order
    """, (learner_id, course_id)).fetchall()

    cards = []
    for outcome in outcomes:
        unlocked = is_outcome_unlocked(conn, learner_id, outcome)
        cards.append({"outcome": outcome, "unlocked": unlocked})

    conn.close()
    return render_template("learning/pathway.html", course=course, cards=cards)


@learning_bp.route("/outcome/<int:outcome_id>")
@role_required("learner")
def outcome(outcome_id):
    learner_id = session["user_id"]
    conn = get_db()

    outcome = conn.execute("""
        SELECT
            lo.*, c.course_id, c.course_title, s.subject_name,
            lessons.lesson_id, lessons.lesson_title, lessons.lesson_content,
            lessons.estimated_minutes,
            COALESCE(mr.pretest_score, 0) AS pretest_score,
            COALESCE(mr.practice_score, 0) AS practice_score,
            COALESCE(mr.posttest_score, 0) AS posttest_score,
            COALESCE(mr.improvement_score, 0) AS improvement_score,
            COALESCE(mr.mastery_score, 0) AS mastery_score,
            COALESCE(mr.mastery_status, 'Not Started') AS mastery_status,
            COALESCE(mr.mastery_level, 'Beginning') AS mastery_level
        FROM learning_outcomes lo
        JOIN lessons ON lessons.outcome_id = lo.outcome_id
        JOIN courses c ON lessons.course_id = c.course_id
        JOIN subjects s ON c.subject_id = s.subject_id
        LEFT JOIN mastery_records mr
            ON mr.outcome_id = lo.outcome_id AND mr.learner_id = ?
        WHERE lo.outcome_id = ?
    """, (learner_id, outcome_id)).fetchone()

    if not outcome:
        conn.close()
        return "Outcome not found", 404

    if not is_outcome_unlocked(conn, learner_id, outcome):
        conn.close()
        flash("This learning outcome is locked. Master the previous outcome first.", "warning")
        return redirect(url_for("learning.pathway", course_id=outcome["course_id"]))

    pretest = get_assessment(conn, outcome["lesson_id"], "pretest")
    practice = get_assessment(conn, outcome["lesson_id"], "practice")
    posttest = get_assessment(conn, outcome["lesson_id"], "posttest")

    pretest_attempt = get_latest_attempt(conn, learner_id, pretest["assessment_id"]) if pretest else None
    practice_attempt = get_latest_attempt(conn, learner_id, practice["assessment_id"]) if practice else None
    posttest_attempt = get_latest_attempt(conn, learner_id, posttest["assessment_id"]) if posttest else None

    required_concepts = get_required_concepts(conn, outcome_id)
    concept_map = get_concept_mastery(conn, learner_id, outcome_id)
    posttest_unlocked, unlock_blockers = posttest_unlock_status(conn, learner_id, outcome_id, required_concepts)
    system_blockers, concepts_not_ready = split_posttest_blockers(unlock_blockers)
    posttest_blockers = describe_posttest_blockers(unlock_blockers)
    needs_more_practice = bool(concepts_not_ready) or "practice_required" in system_blockers

    weak_concepts = get_latest_weak_concepts(conn, learner_id, outcome_id, pretest_attempt, required_concepts)
    if not posttest_unlocked:
        if concepts_not_ready:
            weak_concepts = concepts_not_ready
        elif system_blockers and not needs_more_practice:
            weak_concepts = []

    placeholders = ",".join("?" for _ in weak_concepts) if weak_concepts else "''"
    params = [outcome_id] + weak_concepts
    notes = conn.execute(f"""
        SELECT * FROM adaptive_notes
        WHERE outcome_id = ? AND concept_tag IN ({placeholders})
        ORDER BY priority, concept_tag
    """, params).fetchall() if weak_concepts else []
    videos = conn.execute(f"""
        SELECT * FROM adaptive_videos
        WHERE outcome_id = ? AND concept_tag IN ({placeholders})
        ORDER BY concept_tag
    """, params).fetchall() if weak_concepts else []

    illustrations = conn.execute(f"""
        SELECT * FROM learning_resources
        WHERE outcome_id = ?
          AND concept_tag IN ({placeholders})
          AND resource_type IN ('concept_map', 'simulation')
        ORDER BY concept_tag, resource_id
    """, params).fetchall() if weak_concepts else conn.execute("""
        SELECT * FROM learning_resources
        WHERE outcome_id = ?
          AND resource_type IN ('concept_map', 'simulation')
        ORDER BY concept_tag, resource_id
        LIMIT 6
    """, (outcome_id,)).fetchall()

    worked_examples = conn.execute(f"""
        SELECT * FROM worked_examples
        WHERE outcome_id = ? AND concept_tag IN ({placeholders})
        ORDER BY concept_tag, example_id
    """, params).fetchall() if weak_concepts else conn.execute("""
        SELECT * FROM worked_examples
        WHERE outcome_id = ?
        ORDER BY concept_tag, example_id
        LIMIT 4
    """, (outcome_id,)).fetchall()

    performance_resources = conn.execute("""
        SELECT * FROM learning_resources
        WHERE outcome_id = ?
          AND resource_type IN ('project', 'investigation', 'experiment', 'activity', 'remediation', 'enrichment')
        ORDER BY
            CASE resource_type
                WHEN 'project' THEN 1
                WHEN 'investigation' THEN 2
                WHEN 'experiment' THEN 3
                WHEN 'activity' THEN 4
                WHEN 'remediation' THEN 5
                ELSE 6
            END,
            resource_id
    """, (outcome_id,)).fetchall()

    activities = conn.execute("""
        SELECT * FROM learning_activities
        WHERE outcome_id = ?
        ORDER BY activity_id
    """, (outcome_id,)).fetchall()
    activity_submissions = activity_submission_map(conn, learner_id, outcome_id)
    activity_cards = []
    for activity in activities:
        submission = activity_submissions.get(activity["activity_id"])
        activity_cards.append({
            "activity": activity,
            "guidance": guidance_for_activity(activity["activity_type"]),
            "submission_count": submission["submission_count"] if submission else 0,
            "latest_submission": submission["latest_submission"] if submission else None,
        })

    practical_evidence = latest_practical_evidence(conn, learner_id, outcome_id)
    bkt_rows = bkt_summary(conn, learner_id, outcome_id)
    concepts_resolved = weak_concepts_resolved(conn, learner_id, outcome_id)

    latest_recommendation = conn.execute("""
        SELECT recommendation_reason, recommendation_type, evidence_used, expected_mastery,
               estimated_study_minutes, recommended_resource, recommended_activity,
               teacher_action_required, teacher_status, created_at
        FROM recommendations
        WHERE learner_id = ? AND outcome_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (learner_id, outcome_id)).fetchone()

    reflection = latest_reflection(conn, learner_id, outcome_id)
    evidence = evidence_checklist(
        pretest_attempt,
        practice_attempt,
        posttest_attempt,
        concepts_resolved,
        bool(reflection),
        outcome["posttest_score"],
        outcome["mastery_threshold"],
        bool(practical_evidence) if outcome["practical_required"] else True,
    )
    progress = evidence_progress(conn, learner_id, outcome_id, bool(outcome["practical_required"]))

    pretest_items = prepare_question_items(conn, pretest["assessment_id"], limit=6, learner_id=learner_id) if pretest else []
    practice_items = []
    if practice and pretest_attempt and not posttest_unlocked and needs_more_practice:
        practice_items = prepare_question_items(conn, practice["assessment_id"], concept_tags=weak_concepts or None, limit=6, learner_id=learner_id)
    elif practice and pretest_attempt and posttest_unlocked:
        practice_items = prepare_question_items(conn, practice["assessment_id"], limit=6, learner_id=learner_id)
    posttest_items = prepare_question_items(conn, posttest["assessment_id"], limit=8, learner_id=learner_id) if posttest and posttest_unlocked else []

    if not pretest_attempt:
        stage = "pretest"
    elif not posttest_unlocked:
        stage = "adaptive_practice"
    elif not posttest_attempt:
        stage = "posttest"
    elif outcome["mastery_status"] != "Mastered":
        stage = "remediation"
    else:
        stage = "mastered"

    conn.close()
    return render_template(
        "learning/outcome.html",
        outcome=outcome,
        pretest=pretest,
        practice=practice,
        posttest=posttest,
        pretest_attempt=pretest_attempt,
        practice_attempt=practice_attempt,
        posttest_attempt=posttest_attempt,
        pretest_items=pretest_items,
        practice_items=practice_items,
        posttest_items=posttest_items,
        notes=notes,
        videos=videos,
        illustrations=illustrations,
        activities=activities,
        activity_cards=activity_cards,
        weak_concepts=weak_concepts,
        required_concepts=required_concepts,
        concept_map=concept_map,
        posttest_unlocked=posttest_unlocked,
        concepts_not_ready=concepts_not_ready,
        posttest_blockers=posttest_blockers,
        needs_more_practice=needs_more_practice,
        latest_recommendation=latest_recommendation,
        reflection=reflection,
        practical_evidence=practical_evidence,
        evidence_progress=progress,
        evidence_type_labels=EVIDENCE_TYPE_LABELS,
        worked_examples=worked_examples,
        performance_resources=performance_resources,
        bkt_rows=bkt_rows,
        evidence=evidence,
        stage=stage,
        practice_threshold=PRACTICE_CONCEPT_THRESHOLD,
    )


@learning_bp.route("/outcome/<int:outcome_id>/reflection", methods=["POST"])
@role_required("learner")
@csrf_protect
def submit_reflection(outcome_id):
    learner_id = session["user_id"]
    reflection_text = (request.form.get("reflection_text") or "").strip()
    difficult_concept = (request.form.get("difficult_concept") or "").strip()
    helpful_strategy = (request.form.get("helpful_strategy") or "").strip()
    real_life_application = (request.form.get("real_life_application") or "").strip()
    support_needed = (request.form.get("support_needed") or "").strip()
    confidence_level = int(request.form.get("confidence_level") or 3)

    if not reflection_text:
        flash("Please write a short reflection before continuing to post-test.", "warning")
        return redirect(url_for("learning.outcome", outcome_id=outcome_id))

    conn = get_db()
    conn.execute("""
        INSERT INTO learning_reflections
        (learner_id, outcome_id, reflection_text, difficult_concept, helpful_strategy,
         real_life_application, support_needed, confidence_level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        learner_id,
        outcome_id,
        reflection_text,
        difficult_concept,
        helpful_strategy,
        real_life_application,
        support_needed,
        confidence_level,
    ))
    conn.execute("""
        INSERT INTO activity_logs (learner_id, activity_type, activity_description)
        VALUES (?, ?, ?)
    """, (learner_id, "Reflection Submitted", f"Reflection added for outcome {outcome_id}."))
    conn.commit()
    conn.close()
    flash("Reflection saved. If your practice evidence is complete, the post-test will now unlock.", "success")
    return redirect(url_for("learning.outcome", outcome_id=outcome_id))


@learning_bp.route("/outcome/<int:outcome_id>/evidence", methods=["POST"])
@role_required("learner")
@csrf_protect
def submit_outcome_evidence(outcome_id):
    learner_id = session["user_id"]
    evidence_type = (request.form.get("evidence_type") or "activity").strip().lower()
    if evidence_type not in EVIDENCE_TYPE_LABELS:
        evidence_type = "activity"

    title = (request.form.get("evidence_title") or EVIDENCE_TYPE_LABELS[evidence_type]).strip()
    description = (request.form.get("evidence_description") or "").strip()
    simulate_offline = bool(request.form.get("simulate_offline"))
    file = request.files.get("evidence_file")

    if not description and not (file and file.filename):
        flash("Please describe the evidence or upload a file before submitting.", "warning")
        return redirect(url_for("learning.outcome", outcome_id=outcome_id))

    file_path, file_type, file_size, upload_error = save_evidence_file(file, learner_id, outcome_id)
    if upload_error:
        flash(upload_error, "danger")
        return redirect(url_for("learning.outcome", outcome_id=outcome_id))

    conn = get_db()
    meta = outcome_meta(conn, outcome_id)
    if not meta:
        conn.close()
        return "Learning outcome not found", 404

    entity_type = "evidence"
    entity_id = outcome_id
    event_payload = {"outcome_id": outcome_id, "title": title, "evidence_type": evidence_type}
    activity_id = request.form.get("activity_id")

    if evidence_type == "activity" or (evidence_type in {"project", "investigation"} and activity_id and str(activity_id).isdigit()):
        if not activity_id or not str(activity_id).isdigit():
            conn.close()
            flash("Please choose the activity, project, investigation, or task this evidence belongs to.", "warning")
            return redirect(url_for("learning.outcome", outcome_id=outcome_id))

        activity = conn.execute("""
            SELECT activity_id, outcome_id, activity_title, activity_type
            FROM learning_activities
            WHERE activity_id=? AND outcome_id=?
        """, (int(activity_id), outcome_id)).fetchone()
        if not activity:
            conn.close()
            flash("Selected activity was not found for this learning outcome.", "warning")
            return redirect(url_for("learning.outcome", outcome_id=outcome_id))

        cur = conn.execute("""
            INSERT INTO activity_submissions
            (learner_id, activity_id, outcome_id, submission_text, evidence_path, submission_status)
            VALUES (?, ?, ?, ?, ?, 'Submitted')
        """, (learner_id, activity["activity_id"], outcome_id, description or title, file_path))
        entity_type = "activity_submission"
        entity_id = cur.lastrowid
        event_payload.update({"submission_id": entity_id, "activity_id": activity["activity_id"]})
        portfolio_type = f"{activity['activity_type']} Evidence"
        portfolio_note = f"{activity['activity_title']}: {description or title}"
        log_type = "Activity Evidence Submitted"
        audit_action = "ACTIVITY_SUBMISSION"

    elif evidence_type == "reflection":
        confidence_level = int(request.form.get("confidence_level") or 3)
        conn.execute("""
            INSERT INTO learning_reflections
            (learner_id, outcome_id, reflection_text, confidence_level)
            VALUES (?, ?, ?, ?)
        """, (learner_id, outcome_id, description or title, confidence_level))
        portfolio_type = "Reflection Evidence"
        portfolio_note = description or title
        log_type = "Reflection Submitted"
        audit_action = "REFLECTION_SUBMITTED"

    else:
        evidence_label = EVIDENCE_TYPE_LABELS[evidence_type]
        cur = conn.execute("""
            INSERT INTO practical_evidence
            (learner_id, subject_id, topic_id, outcome_id, competency_id,
             evidence_title, evidence_description, file_path, file_type, file_size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            learner_id,
            meta["subject_id"],
            meta["topic_id"],
            outcome_id,
            meta["competency_id"],
            title or evidence_label,
            description,
            file_path,
            file_type,
            file_size,
        ))
        entity_type = "practical_evidence"
        entity_id = cur.lastrowid
        event_payload.update({"practical_id": entity_id})
        portfolio_type = evidence_label
        portfolio_note = description or title
        log_type = f"{evidence_label} Submitted"
        audit_action = "RESOURCE_UPLOAD"

    conn.execute("""
        INSERT INTO evidence_portfolio (learner_id, outcome_id, evidence_type, evidence_status, evidence_note)
        VALUES (?, ?, ?, 'Submitted', ?)
    """, (learner_id, outcome_id, portfolio_type, portfolio_note))
    conn.execute("""
        INSERT INTO activity_logs (learner_id, activity_type, activity_description)
        VALUES (?, ?, ?)
    """, (learner_id, log_type, portfolio_note))
    conn.execute("""
        INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details)
        VALUES (?, ?, ?, ?, ?)
    """, (learner_id, audit_action, entity_type, entity_id, f"{portfolio_type}: {portfolio_note}"))

    if simulate_offline:
        queue_offline_event(conn, learner_id, "evidence_submission", event_payload)

    progress = evidence_progress(
        conn,
        learner_id,
        outcome_id,
        bool(conn.execute("SELECT practical_required FROM learning_outcomes WHERE outcome_id=?", (outcome_id,)).fetchone()["practical_required"]),
    )
    conn.commit()
    conn.close()
    flash(f"{portfolio_type} saved. Evidence progress is now {progress['percentage']}%.", "success")
    return redirect(url_for("learning.outcome", outcome_id=outcome_id))


@learning_bp.route("/outcome/<int:outcome_id>/practical-evidence", methods=["POST"])
@role_required("learner")
@csrf_protect
def submit_practical_evidence(outcome_id):
    learner_id = session["user_id"]
    title = (request.form.get("evidence_title") or "Practical Evidence").strip()
    description = (request.form.get("evidence_description") or "").strip()
    file = request.files.get("evidence_file")
    file_path = None
    file_type = None
    file_size = 0

    if file and file.filename:
        if not allowed_upload(file.filename):
            flash("Unsupported evidence file type. Please upload a PDF, image, text, Word, Python, or ZIP file.", "danger")
            return redirect(url_for("learning.outcome", outcome_id=outcome_id))
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "practical_evidence")
        os.makedirs(upload_dir, exist_ok=True)
        filename = secure_filename(f"learner_{learner_id}_outcome_{outcome_id}_" + file.filename)
        absolute_path = os.path.join(upload_dir, filename)
        file.save(absolute_path)
        file_path = os.path.join("uploads", "practical_evidence", filename)
        file_type = os.path.splitext(filename)[1].lower()
        file_size = os.path.getsize(absolute_path)

    conn = get_db()
    meta = conn.execute("""
        SELECT lo.outcome_id, lo.topic_id, lo.competency_id, c.subject_id
        FROM learning_outcomes lo
        JOIN competencies c ON c.competency_id=lo.competency_id
        WHERE lo.outcome_id=?
    """, (outcome_id,)).fetchone()
    conn.execute("""
        INSERT INTO practical_evidence
        (learner_id, subject_id, topic_id, outcome_id, competency_id,
         evidence_title, evidence_description, file_path, file_type, file_size_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        learner_id,
        meta["subject_id"] if meta else None,
        meta["topic_id"] if meta else None,
        outcome_id,
        meta["competency_id"] if meta else None,
        title,
        description,
        file_path,
        file_type,
        file_size,
    ))
    practical_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("""
        INSERT INTO evidence_portfolio (learner_id, outcome_id, evidence_type, evidence_status, evidence_note)
        VALUES (?, ?, 'Practical Evidence', 'Submitted', ?)
    """, (learner_id, outcome_id, description or title))
    conn.execute("""
        INSERT INTO activity_logs (learner_id, activity_type, activity_description)
        VALUES (?, ?, ?)
    """, (learner_id, "Practical Evidence Submitted", f"Practical evidence added for outcome {outcome_id}."))
    conn.execute("""
        INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details)
        VALUES (?, 'RESOURCE_UPLOAD', 'practical_evidence', ?, ?)
    """, (learner_id, practical_id, f"Uploaded practical evidence '{title}' for outcome {outcome_id}"))
    if request.form.get("simulate_offline"):
        queue_offline_event(conn, learner_id, "practical_evidence_submission", {
            "practical_id": practical_id,
            "outcome_id": outcome_id,
            "title": title,
        })
    conn.commit()
    conn.close()
    flash("Practical evidence submitted for teacher review.", "success")
    return redirect(url_for("learning.outcome", outcome_id=outcome_id))


@learning_bp.route("/activity/<int:activity_id>/submit", methods=["POST"])
@role_required("learner")
@csrf_protect
def submit_activity(activity_id):
    learner_id = session["user_id"]
    submission_text = (request.form.get("submission_text") or "").strip()
    simulate_offline = bool(request.form.get("simulate_offline"))
    if not submission_text:
        flash("Please describe the evidence you produced for the activity.", "warning")
        return redirect(request.referrer or url_for("student.student_dashboard"))

    conn = get_db()
    activity = conn.execute("""
        SELECT activity_id, outcome_id, activity_title, activity_type
        FROM learning_activities
        WHERE activity_id=?
    """, (activity_id,)).fetchone()
    if not activity:
        conn.close()
        flash("Activity was not found.", "warning")
        return redirect(url_for("student.student_dashboard"))

    cur = conn.execute("""
        INSERT INTO activity_submissions
        (learner_id, activity_id, outcome_id, submission_text, submission_status)
        VALUES (?, ?, ?, ?, 'Submitted')
    """, (learner_id, activity_id, activity["outcome_id"], submission_text))
    submission_id = cur.lastrowid
    conn.execute("""
        INSERT INTO evidence_portfolio (learner_id, outcome_id, evidence_type, evidence_status, evidence_note)
        VALUES (?, ?, 'Learning Activity', 'Submitted', ?)
    """, (learner_id, activity["outcome_id"], activity["activity_title"]))
    conn.execute("""
        INSERT INTO activity_logs (learner_id, activity_type, activity_description)
        VALUES (?, ?, ?)
    """, (learner_id, "Activity Submitted", activity["activity_title"]))
    conn.execute("""
        INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details)
        VALUES (?, 'ACTIVITY_SUBMISSION', 'activity_submission', ?, ?)
    """, (learner_id, submission_id, f"Submitted activity evidence for {activity['activity_title']}"))
    if simulate_offline:
        queue_offline_event(conn, learner_id, "activity_submission", {
            "submission_id": submission_id,
            "activity_id": activity_id,
            "outcome_id": activity["outcome_id"],
        })
    conn.commit()
    conn.close()
    flash("Activity evidence submitted for teacher review.", "success")
    return redirect(url_for("learning.outcome", outcome_id=activity["outcome_id"]))


@learning_bp.route("/assessment/<int:assessment_id>/submit", methods=["POST"])
@role_required("learner")
@csrf_protect
def submit_assessment(assessment_id):
    learner_id = session["user_id"]
    conn = get_db()

    assessment = conn.execute("""
        SELECT assessments.*, lessons.outcome_id, lessons.lesson_id, lo.outcome_name,
               lo.mastery_threshold, lo.practical_required, lo.teacher_review_required
        FROM assessments
        JOIN lessons ON assessments.lesson_id = lessons.lesson_id
        JOIN learning_outcomes lo ON lessons.outcome_id = lo.outcome_id
        WHERE assessments.assessment_id = ?
    """, (assessment_id,)).fetchone()

    if not assessment:
        conn.close()
        return "Assessment not found", 404

    required_concepts = get_required_concepts(conn, assessment["outcome_id"])
    if assessment["assessment_type"] == "posttest":
        unlocked, not_ready = posttest_unlock_status(conn, learner_id, assessment["outcome_id"], required_concepts)
        if not unlocked:
            conn.close()
            flash("Post-test is locked. " + posttest_blocker_summary(not_ready), "warning")
            return redirect(url_for("learning.outcome", outcome_id=assessment["outcome_id"]))

    questions = conn.execute("""
        SELECT question_id, question_text, concept_tag, question_type, correct_answer, marks
        FROM questions
        WHERE assessment_id = ?
        ORDER BY question_id
    """, (assessment_id,)).fetchall()

    correct_count = 0
    weak_concepts = []
    answered_questions = []
    concept_stats = defaultdict(lambda: {"correct": 0, "total": 0})

    cur = conn.execute("""
        INSERT INTO assessment_attempts (learner_id, assessment_id, score, weak_concepts)
        VALUES (?, ?, 0, '')
    """, (learner_id, assessment_id))
    attempt_id = cur.lastrowid

    for q in questions:
        selected = request.form.get(f"question_{q['question_id']}")
        if selected is None:
            continue

        question_type = q["question_type"] or "multiple_choice"
        selected_option_id = None
        if question_type == "multiple_choice" and str(selected).isdigit():
            selected_option_id = int(selected)
            correct_option = conn.execute("""
                SELECT option_id FROM question_options
                WHERE question_id = ? AND is_correct = 1
                LIMIT 1
            """, (q["question_id"],)).fetchone()
            is_correct = bool(correct_option and selected_option_id == correct_option["option_id"])
        else:
            expected = (q["correct_answer"] or "").strip().lower()
            observed = str(selected or "").strip().lower()
            is_correct = bool(expected and observed == expected)
        answered_questions.append(q)
        concept_stats[q["concept_tag"]]["total"] += 1
        if is_correct:
            correct_count += 1
            concept_stats[q["concept_tag"]]["correct"] += 1
        else:
            weak_concepts.append(q["concept_tag"])

        conn.execute("""
            INSERT INTO attempt_answers (attempt_id, question_id, selected_option_id, selected_response, is_correct)
            VALUES (?, ?, ?, ?, ?)
        """, (attempt_id, q["question_id"], selected_option_id, str(selected), 1 if is_correct else 0))

        # V8: update simplified Bayesian Knowledge Tracing probability for the concept.
        update_bkt_record(conn, learner_id, assessment["outcome_id"], q["concept_tag"], is_correct)

    weak_concepts = sorted(set(weak_concepts))
    score = calculate_percentage(correct_count, len(answered_questions))
    weak_text = ",".join(weak_concepts)
    conn.execute("UPDATE assessment_attempts SET score = ?, weak_concepts = ? WHERE attempt_id = ?", (score, weak_text, attempt_id))

    update_concept_mastery(conn, learner_id, assessment["outcome_id"], assessment["assessment_type"], concept_stats)

    existing = conn.execute("""
        SELECT * FROM mastery_records WHERE learner_id = ? AND outcome_id = ?
    """, (learner_id, assessment["outcome_id"])).fetchone()

    pre = existing["pretest_score"] if existing else 0
    practice = existing["practice_score"] if existing else 0
    post = existing["posttest_score"] if existing else 0
    mastery_score = existing["mastery_score"] if existing else 0
    improvement = existing["improvement_score"] if existing else 0
    status = existing["mastery_status"] if existing else "In Progress"
    level = existing["mastery_level"] if existing else "Beginning"
    unlock_blockers = []

    if assessment["assessment_type"] == "pretest":
        pre = score
        status = "Practice Required"
        level = mastery_level(score)
    elif assessment["assessment_type"] == "practice":
        practice = score
        unlocked, unlock_blockers = posttest_unlock_status(conn, learner_id, assessment["outcome_id"], required_concepts)
        _, concept_blockers = split_posttest_blockers(unlock_blockers)
        status = "Ready for Post-test" if unlocked else "Practice Required"
        level = mastery_level(score)
        if concept_blockers:
            weak_concepts = concept_blockers
    elif assessment["assessment_type"] == "posttest":
        post = score
        pretest_attempt_for_evidence, _ = get_pretest_weak_concepts(conn, learner_id, assessment["outcome_id"])
        mastery_result = evidence_based_mastery(
            pretest_done=pretest_attempt_for_evidence is not None,
            activity_done=has_reflection(conn, learner_id, assessment["outcome_id"]),
            practice_score=practice,
            weak_concepts_resolved=weak_concepts_resolved(conn, learner_id, assessment["outcome_id"]),
            posttest_score=post,
            practical_done=practical_evidence_done(conn, learner_id, assessment["outcome_id"]),
            practical_required=bool(assessment["practical_required"]),
            teacher_review_required=bool(assessment["teacher_review_required"]),
            teacher_verified=False,
            threshold=assessment["mastery_threshold"],
        )
        mastery_score = mastery_result["ai_confidence"]
        improvement = 0
        status = mastery_result["mastery_status"]
        level = mastery_result["mastery_level"]

    conn.execute("""
        INSERT INTO mastery_records
        (learner_id, outcome_id, pretest_score, practice_score, posttest_score, improvement_score,
         mastery_score, mastery_level, mastery_status, is_unlocked)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(learner_id, outcome_id)
        DO UPDATE SET
            pretest_score = excluded.pretest_score,
            practice_score = excluded.practice_score,
            posttest_score = excluded.posttest_score,
            improvement_score = excluded.improvement_score,
            mastery_score = excluded.mastery_score,
            mastery_level = excluded.mastery_level,
            mastery_status = excluded.mastery_status,
            is_unlocked = 1,
            updated_at = CURRENT_TIMESTAMP
    """, (learner_id, assessment["outcome_id"], pre, practice, post, improvement, mastery_score, level, status))

    rec = build_recommendation(
        assessment["outcome_name"],
        assessment["assessment_type"],
        score,
        weak_concepts,
        mastery_score if assessment["assessment_type"] == "posttest" else None,
    )

    if assessment["assessment_type"] == "practice":
        if weak_concepts:
            rec["reason"] += " The next practice set will focus only on these weak concept(s): " + ", ".join(weak_concepts) + "."
        if unlock_blockers:
            rec["reason"] += " Pending before post-test: " + posttest_blocker_summary(unlock_blockers)

    conn.execute("""
        INSERT INTO recommendations
        (learner_id, lesson_id, outcome_id, recommendation_reason, recommendation_type,
         evidence_used, weak_concepts, strong_concepts, confidence_score, expected_mastery,
         estimated_study_minutes, recommended_resource, recommended_activity, teacher_action_required)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        learner_id,
        assessment["lesson_id"],
        assessment["outcome_id"],
        rec["reason"],
        rec["type"],
        rec.get("evidence_used"),
        rec.get("weak_concepts"),
        rec.get("strong_concepts"),
        rec.get("confidence_score", 0),
        rec.get("expected_mastery", 0),
        rec.get("estimated_study_minutes", 0),
        rec.get("recommended_resource"),
        rec.get("recommended_activity"),
        1 if rec.get("teacher_action_required") else 0,
    ))
    recommendation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    current_evidence = {
        "pretest_completed": pre > 0 or assessment["assessment_type"] == "pretest",
        "adaptive_practice_completed": practice >= PRACTICE_CONCEPT_THRESHOLD,
        "reflection_completed": has_reflection(conn, learner_id, assessment["outcome_id"]),
        "weak_concepts_resolved": weak_concepts_resolved(conn, learner_id, assessment["outcome_id"]),
        "posttest_passed": post >= assessment["mastery_threshold"],
    }
    ai_exp = build_ai_explanation(assessment["outcome_name"], assessment["assessment_type"], score, weak_concepts, current_evidence, status)
    record_ai_explanation(
        conn, learner_id, assessment["outcome_id"], ai_exp["decision"],
        ai_exp["evidence_used"], ai_exp["explanation"], mastery_score if assessment["assessment_type"] == "posttest" else score
    )

    conn.execute("""
        INSERT INTO activity_logs (learner_id, activity_type, activity_description)
        VALUES (?, ?, ?)
    """, (learner_id, f"{assessment['assessment_type'].title()} Submitted", f"Score {score}%. Status: {status}."))
    conn.execute("""
        INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details)
        VALUES (?, ?, 'assessment_attempt', ?, ?)
    """, (learner_id, "ASSESSMENT_SUBMITTED", attempt_id, f"{assessment['assessment_type']} submitted with computed score {score}% and status {status}"))
    conn.execute("""
        INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details)
        VALUES (?, 'AI_RECOMMENDATION_GENERATED', 'recommendation', ?, ?)
    """, (learner_id, recommendation_id, rec["reason"]))
    refresh_learner_profile(conn, learner_id)

    if assessment["assessment_type"] == "posttest" and status == "Mastered":
        next_outcome = conn.execute("""
            SELECT next.outcome_id
            FROM learning_outcomes current
            JOIN learning_outcomes next
                ON next.competency_id = current.competency_id
               AND next.sequence_order = current.sequence_order + 1
            WHERE current.outcome_id = ?
        """, (assessment["outcome_id"],)).fetchone()
        if next_outcome:
            conn.execute("""
                INSERT INTO mastery_records
                (learner_id, outcome_id, mastery_score, mastery_level, mastery_status, is_unlocked)
                VALUES (?, ?, 0, 'Beginning', 'Not Started', 1)
                ON CONFLICT(learner_id, outcome_id)
                DO UPDATE SET is_unlocked = 1, updated_at = CURRENT_TIMESTAMP
            """, (learner_id, next_outcome["outcome_id"]))

    conn.commit()
    conn.close()

    if assessment["assessment_type"] == "pretest":
        flash(f"Pre-test submitted: {score}%. Adaptive learning has selected weak concept practice.", "success")
    elif assessment["assessment_type"] == "practice":
        if status == "Ready for Post-test":
            flash(f"Practice submitted: {score}%. All concepts reached {PRACTICE_CONCEPT_THRESHOLD}%+. Post-test unlocked.", "success")
        else:
            flash(f"Practice submitted: {score}%. Post-test is still locked. {posttest_blocker_summary(unlock_blockers)}", "warning")
    else:
        flash(f"Post-test submitted: {score}%. Algorithm mastery: {mastery_score}%. Status: {status}.", "success")

    return redirect(url_for("learning.outcome", outcome_id=assessment["outcome_id"]))

@learning_bp.route("/sync/assessments", methods=["POST"])
@role_required("learner")
@csrf_protect
def sync_assessments():
    learner_id = session["user_id"]
    data = request.json
    if not data or "attempts" not in data:
        return {"error": "Invalid data"}, 400

    conn = get_db()
    for attempt in data["attempts"]:
        # Idempotent sync logic for offline attempts
        # In a real app, we would use the timestamp to avoid duplicates
        pass
    conn.close()
    return {"status": "success"}
