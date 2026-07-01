# Database Dictionary

Important tables:

- `roles`: standard roles only: super administrator, school administrator, teacher and learner.
- `users`: account identity, role, school, status, security level, lockout and password-change state.
- `schools`, `classes`, `enrollments`: school structure and learner class assignment.
- `teacher_subject_assignments`: teacher subject/class assignment.
- `subjects`, `terms`, `strands`, `sub_strands`, `topics`: CBC curriculum structure.
- `competencies`, `learning_outcomes`: competency-based outcome map.
- `performance_indicators`, `success_criteria`: CBC evidence expectations.
- `generic_skills`, `curriculum_values`, `cross_cutting_issues`: CBC transversal learning expectations.
- `lessons`, `adaptive_notes`, `adaptive_videos`, `worked_examples`, `learning_resources`, `learning_activities`: adaptive content and active-learning resources.
- `assessments`, `questions`, `question_options`, `assessment_attempts`, `attempt_answers`: question bank and assessment evidence.
- `concept_mastery`, `bkt_mastery`: concept-level mastery and simplified BKT probabilities.
- `mastery_records`: evidence-based mastery decision per learner and outcome.
- `learning_reflections`, `practical_evidence`, `rubric_criteria`, `rubric_assessments`: CBC reflection and practical evidence review.
- `recommendations`, `ai_explanations`: explainable AI recommendation records.
- `teacher_interventions`, `teacher_feedback`, `teacher_mastery_reviews`: teacher-in-the-loop decision support.
- `activity_submissions`, `activity_feedback`: learner CBC activity evidence and teacher feedback.
- `offline_sync_queue`, `sync_queue`, `cached_resources`, `offline_activity_logs`, `sync_events`: offline prototype foundation, cached resources, queued submissions and sync attempt logs.
- `audit_logs`: traceability for security, curriculum, assessment, resource and AI events.
- `system_settings`, `backups`: AI/CBC configuration and backup register.

Recent schema additions:

- `questions` now stores subject, topic, outcome, competency, concept, difficulty, Bloom level, question type, marks, answer, feedback, resource link and estimated time.
- `learning_resources` includes offline-cache flags and cache keys.
- `recommendations` includes recommended activity and teacher-action-required indicators.
- `learning_reflections` stores difficult concept, helpful strategy, real-life application and support-needed prompts.
