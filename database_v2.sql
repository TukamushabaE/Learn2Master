PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS sync_events;
DROP TABLE IF EXISTS offline_activity_logs;
DROP TABLE IF EXISTS sync_queue;
DROP TABLE IF EXISTS system_settings;
DROP TABLE IF EXISTS backups;
DROP TABLE IF EXISTS cached_resources;
DROP TABLE IF EXISTS offline_sync_queue;
DROP TABLE IF EXISTS rubric_assessments;
DROP TABLE IF EXISTS rubric_criteria;
DROP TABLE IF EXISTS teacher_mastery_reviews;
DROP TABLE IF EXISTS teacher_subject_assignments;
DROP TABLE IF EXISTS outcome_cross_cutting_issues;
DROP TABLE IF EXISTS outcome_values;
DROP TABLE IF EXISTS outcome_generic_skills;
DROP TABLE IF EXISTS cross_cutting_issues;
DROP TABLE IF EXISTS curriculum_values;
DROP TABLE IF EXISTS generic_skills;
DROP TABLE IF EXISTS success_criteria;
DROP TABLE IF EXISTS performance_indicators;
DROP TABLE IF EXISTS sub_strands;
DROP TABLE IF EXISTS strands;
DROP TABLE IF EXISTS terms;
DROP TABLE IF EXISTS bkt_mastery;
DROP TABLE IF EXISTS practical_evidence;
DROP TABLE IF EXISTS worked_examples;
DROP TABLE IF EXISTS ai_explanations;
DROP TABLE IF EXISTS evidence_portfolio;
DROP TABLE IF EXISTS teacher_feedback;
DROP TABLE IF EXISTS teacher_interventions;
DROP TABLE IF EXISTS learning_reflections;
DROP TABLE IF EXISTS learner_profiles;
DROP TABLE IF EXISTS learning_resources;
DROP TABLE IF EXISTS concepts;
DROP TABLE IF EXISTS activity_feedback;
DROP TABLE IF EXISTS activity_submissions;
DROP TABLE IF EXISTS activity_logs;
DROP TABLE IF EXISTS recommendations;
DROP TABLE IF EXISTS concept_mastery;
DROP TABLE IF EXISTS mastery_records;
DROP TABLE IF EXISTS attempt_answers;
DROP TABLE IF EXISTS assessment_attempts;
DROP TABLE IF EXISTS question_options;
DROP TABLE IF EXISTS questions;
DROP TABLE IF EXISTS assessments;
DROP TABLE IF EXISTS adaptive_videos;
DROP TABLE IF EXISTS adaptive_notes;
DROP TABLE IF EXISTS learning_activities;
DROP TABLE IF EXISTS lessons;
DROP TABLE IF EXISTS courses;
DROP TABLE IF EXISTS learning_outcomes;
DROP TABLE IF EXISTS competencies;
DROP TABLE IF EXISTS topics;
DROP TABLE IF EXISTS subjects;
DROP TABLE IF EXISTS enrollments;
DROP TABLE IF EXISTS classes;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS schools;
DROP TABLE IF EXISTS roles;

CREATE TABLE roles (
    role_id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL
);

CREATE TABLE schools (
    school_id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_name TEXT UNIQUE NOT NULL
);

CREATE TABLE users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    phone TEXT,
    title TEXT,
    password_hash TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    school_id INTEGER,
    account_status TEXT DEFAULT 'Pending',
    security_level INTEGER DEFAULT 1,
    must_change_password INTEGER DEFAULT 0,
    failed_login_attempts INTEGER DEFAULT 0,
    locked_until TEXT,
    last_login_at TEXT,
    approved_by INTEGER,
    approved_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (role_id) REFERENCES roles(role_id),
    FOREIGN KEY (school_id) REFERENCES schools(school_id),
    FOREIGN KEY (approved_by) REFERENCES users(user_id)
);

CREATE TABLE classes (
    class_id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT NOT NULL,
    school_id INTEGER NOT NULL,
    FOREIGN KEY (school_id) REFERENCES schools(school_id)
);

CREATE TABLE terms (
    term_id INTEGER PRIMARY KEY AUTOINCREMENT,
    term_name TEXT NOT NULL,
    sequence_order INTEGER DEFAULT 1,
    UNIQUE (term_name)
);

CREATE TABLE enrollments (
    enrollment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    class_id INTEGER NOT NULL,
    enrolled_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (class_id) REFERENCES classes(class_id),
    UNIQUE (learner_id, class_id)
);

CREATE TABLE teacher_subject_assignments (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    class_id INTEGER,
    school_id INTEGER,
    assigned_by INTEGER,
    assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
    FOREIGN KEY (class_id) REFERENCES classes(class_id),
    FOREIGN KEY (school_id) REFERENCES schools(school_id),
    FOREIGN KEY (assigned_by) REFERENCES users(user_id),
    UNIQUE (teacher_id, subject_id, class_id)
);

CREATE TABLE subjects (
    subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_name TEXT UNIQUE NOT NULL
);

CREATE TABLE topics (
    topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    term_id INTEGER,
    topic_title TEXT NOT NULL,
    class_level TEXT DEFAULT 'Senior One',
    curriculum_source TEXT DEFAULT 'Uganda NCDC CBC',
    topic_description TEXT,
    FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
    FOREIGN KEY (term_id) REFERENCES terms(term_id),
    UNIQUE (subject_id, topic_title, class_level)
);

CREATE TABLE strands (
    strand_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    strand_name TEXT NOT NULL,
    strand_description TEXT,
    FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
    UNIQUE (subject_id, strand_name)
);

CREATE TABLE sub_strands (
    sub_strand_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strand_id INTEGER NOT NULL,
    sub_strand_name TEXT NOT NULL,
    sub_strand_description TEXT,
    FOREIGN KEY (strand_id) REFERENCES strands(strand_id),
    UNIQUE (strand_id, sub_strand_name)
);

CREATE TABLE competencies (
    competency_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    topic_id INTEGER,
    sub_strand_id INTEGER,
    competency_code TEXT NOT NULL,
    competency_name TEXT NOT NULL,
    competency_description TEXT,
    FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id),
    FOREIGN KEY (sub_strand_id) REFERENCES sub_strands(sub_strand_id),
    UNIQUE (subject_id, competency_code)
);

CREATE TABLE learning_outcomes (
    outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
    competency_id INTEGER NOT NULL,
    topic_id INTEGER,
    sub_strand_id INTEGER,
    outcome_code TEXT NOT NULL,
    outcome_name TEXT NOT NULL,
    outcome_description TEXT,
    mastery_threshold INTEGER DEFAULT 80,
    practical_required INTEGER DEFAULT 0,
    teacher_review_required INTEGER DEFAULT 0,
    sequence_order INTEGER NOT NULL,
    FOREIGN KEY (competency_id) REFERENCES competencies(competency_id),
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id),
    FOREIGN KEY (sub_strand_id) REFERENCES sub_strands(sub_strand_id),
    UNIQUE (competency_id, outcome_code)
);

CREATE TABLE performance_indicators (
    indicator_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id INTEGER NOT NULL,
    indicator_text TEXT NOT NULL,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE success_criteria (
    criteria_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id INTEGER NOT NULL,
    criteria_text TEXT NOT NULL,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE generic_skills (
    skill_id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT UNIQUE NOT NULL,
    skill_description TEXT
);

CREATE TABLE curriculum_values (
    value_id INTEGER PRIMARY KEY AUTOINCREMENT,
    value_name TEXT UNIQUE NOT NULL,
    value_description TEXT
);

CREATE TABLE cross_cutting_issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_name TEXT UNIQUE NOT NULL,
    issue_description TEXT
);

CREATE TABLE outcome_generic_skills (
    outcome_id INTEGER NOT NULL,
    skill_id INTEGER NOT NULL,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id),
    FOREIGN KEY (skill_id) REFERENCES generic_skills(skill_id),
    UNIQUE (outcome_id, skill_id)
);

CREATE TABLE outcome_values (
    outcome_id INTEGER NOT NULL,
    value_id INTEGER NOT NULL,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id),
    FOREIGN KEY (value_id) REFERENCES curriculum_values(value_id),
    UNIQUE (outcome_id, value_id)
);

CREATE TABLE outcome_cross_cutting_issues (
    outcome_id INTEGER NOT NULL,
    issue_id INTEGER NOT NULL,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id),
    FOREIGN KEY (issue_id) REFERENCES cross_cutting_issues(issue_id),
    UNIQUE (outcome_id, issue_id)
);

CREATE TABLE courses (
    course_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    topic_id INTEGER,
    course_title TEXT NOT NULL,
    course_description TEXT,
    difficulty_level TEXT,
    FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);

CREATE TABLE concepts (
    concept_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id INTEGER NOT NULL,
    concept_tag TEXT NOT NULL,
    concept_title TEXT NOT NULL,
    concept_description TEXT,
    generic_skill TEXT,
    cross_cutting_issue TEXT,
    curriculum_value TEXT,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id),
    UNIQUE (outcome_id, concept_tag)
);

CREATE TABLE lessons (
    lesson_id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    lesson_title TEXT NOT NULL,
    lesson_content TEXT,
    video_url TEXT,
    estimated_minutes INTEGER,
    sequence_order INTEGER NOT NULL,
    FOREIGN KEY (course_id) REFERENCES courses(course_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE learning_activities (
    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id INTEGER NOT NULL,
    activity_title TEXT NOT NULL,
    activity_description TEXT NOT NULL,
    activity_type TEXT DEFAULT 'Practice',
    activity_stage TEXT DEFAULT 'Learning',
    estimated_minutes INTEGER DEFAULT 20,
    evidence_required INTEGER DEFAULT 1,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE adaptive_notes (
    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id INTEGER NOT NULL,
    concept_tag TEXT NOT NULL,
    note_title TEXT NOT NULL,
    note_body TEXT NOT NULL,
    priority INTEGER DEFAULT 1,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE adaptive_videos (
    video_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id INTEGER NOT NULL,
    concept_tag TEXT NOT NULL,
    video_title TEXT NOT NULL,
    video_url TEXT NOT NULL,
    video_description TEXT,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE learning_resources (
    resource_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id INTEGER NOT NULL,
    concept_tag TEXT,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('note','video','worked_example','simulation','activity','project','investigation','experiment','concept_map','homework','extension','remediation','enrichment')),
    resource_title TEXT NOT NULL,
    resource_body TEXT,
    resource_url TEXT,
    estimated_minutes INTEGER DEFAULT 10,
    resource_status TEXT DEFAULT 'Active',
    offline_available INTEGER DEFAULT 0,
    cache_key TEXT,
    last_cached_at TEXT,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE assessments (
    assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id INTEGER NOT NULL,
    assessment_title TEXT NOT NULL,
    assessment_type TEXT NOT NULL CHECK (assessment_type IN ('pretest','practice','posttest')),
    total_marks INTEGER DEFAULT 0,
    FOREIGN KEY (lesson_id) REFERENCES lessons(lesson_id)
);

CREATE TABLE questions (
    question_id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL,
    subject_id INTEGER,
    topic_id INTEGER,
    learning_outcome_id INTEGER,
    competency_id INTEGER,
    concept_id INTEGER,
    question_text TEXT NOT NULL,
    concept_tag TEXT NOT NULL,
    difficulty_level TEXT DEFAULT 'standard',
    question_type TEXT DEFAULT 'multiple_choice',
    marks INTEGER DEFAULT 1,
    correct_answer TEXT,
    bloom_level TEXT DEFAULT 'Understanding',
    explanation TEXT,
    feedback TEXT,
    resource_link TEXT,
    resource_hint TEXT,
    estimated_time_minutes INTEGER DEFAULT 2,
    estimated_time INTEGER DEFAULT 2,
    FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id),
    FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id),
    FOREIGN KEY (learning_outcome_id) REFERENCES learning_outcomes(outcome_id),
    FOREIGN KEY (competency_id) REFERENCES competencies(competency_id),
    FOREIGN KEY (concept_id) REFERENCES concepts(concept_id)
);

CREATE TABLE question_options (
    option_id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    option_text TEXT NOT NULL,
    is_correct INTEGER DEFAULT 0,
    FOREIGN KEY (question_id) REFERENCES questions(question_id)
);

CREATE TABLE assessment_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    assessment_id INTEGER NOT NULL,
    score REAL DEFAULT 0,
    weak_concepts TEXT,
    attempted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id)
);

CREATE TABLE attempt_answers (
    answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    selected_option_id INTEGER,
    selected_response TEXT,
    is_correct INTEGER DEFAULT 0,
    FOREIGN KEY (attempt_id) REFERENCES assessment_attempts(attempt_id),
    FOREIGN KEY (question_id) REFERENCES questions(question_id),
    FOREIGN KEY (selected_option_id) REFERENCES question_options(option_id)
);

CREATE TABLE concept_mastery (
    concept_mastery_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    concept_tag TEXT NOT NULL,
    latest_score REAL DEFAULT 0,
    latest_assessment_type TEXT,
    attempt_count INTEGER DEFAULT 0,
    concept_status TEXT DEFAULT 'Not Practiced',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id),
    UNIQUE (learner_id, outcome_id, concept_tag)
);

CREATE TABLE mastery_records (
    mastery_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    pretest_score REAL DEFAULT 0,
    practice_score REAL DEFAULT 0,
    posttest_score REAL DEFAULT 0,
    improvement_score REAL DEFAULT 0,
    mastery_score REAL DEFAULT 0,
    mastery_level TEXT NOT NULL,
    mastery_status TEXT NOT NULL,
    is_unlocked INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id),
    UNIQUE (learner_id, outcome_id)
);

CREATE TABLE recommendations (
    recommendation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    recommendation_reason TEXT NOT NULL,
    recommendation_type TEXT,
    evidence_used TEXT,
    weak_concepts TEXT,
    strong_concepts TEXT,
    confidence_score REAL DEFAULT 0,
    expected_mastery REAL DEFAULT 0,
    estimated_study_minutes INTEGER DEFAULT 0,
    recommended_resource TEXT,
    recommended_activity TEXT,
    teacher_action_required INTEGER DEFAULT 0,
    teacher_status TEXT DEFAULT 'Pending Review',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (lesson_id) REFERENCES lessons(lesson_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE activity_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    activity_type TEXT NOT NULL,
    activity_description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS activity_submissions (
    submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    activity_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    submission_text TEXT,
    evidence_path TEXT,
    submission_status TEXT DEFAULT 'Submitted',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (activity_id) REFERENCES learning_activities(activity_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE IF NOT EXISTS activity_feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL,
    teacher_id INTEGER NOT NULL,
    feedback_text TEXT NOT NULL,
    rubric_level TEXT DEFAULT 'Developing',
    score INTEGER DEFAULT 0,
    feedback_status TEXT DEFAULT 'Reviewed',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (submission_id) REFERENCES activity_submissions(submission_id),
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);



-- Research-grade alignment tables
CREATE TABLE IF NOT EXISTS learner_profiles (
    profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL UNIQUE,
    class_level TEXT DEFAULT 'Senior One',
    learning_style TEXT DEFAULT 'Adaptive / Mixed',
    learning_pace TEXT DEFAULT 'Not yet classified',
    preferred_support TEXT DEFAULT 'Notes, video and guided practice',
    ai_profile_summary TEXT DEFAULT 'Learner profile will update from assessment evidence.',
    weak_concepts TEXT,
    strong_concepts TEXT,
    confidence_score REAL DEFAULT 0,
    mastery_score REAL DEFAULT 0,
    predicted_performance REAL DEFAULT 0,
    learning_gain REAL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS learning_reflections (
    reflection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    reflection_text TEXT NOT NULL,
    difficult_concept TEXT,
    helpful_strategy TEXT,
    real_life_application TEXT,
    support_needed TEXT,
    confidence_level INTEGER DEFAULT 3,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE IF NOT EXISTS teacher_interventions (
    intervention_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    learner_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    intervention_type TEXT NOT NULL,
    intervention_note TEXT NOT NULL,
    status TEXT DEFAULT 'Assigned',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE IF NOT EXISTS teacher_feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    learner_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    feedback_type TEXT DEFAULT 'General',
    feedback_text TEXT NOT NULL,
    mastery_approval TEXT DEFAULT 'Pending',
    remediation_assigned TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE IF NOT EXISTS evidence_portfolio (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence_status TEXT NOT NULL,
    evidence_note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE IF NOT EXISTS ai_explanations (
    explanation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    decision_type TEXT NOT NULL,
    evidence_used TEXT,
    explanation_text TEXT NOT NULL,
    confidence_score REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE IF NOT EXISTS offline_sync_queue (
    sync_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER,
    event_type TEXT NOT NULL,
    payload TEXT,
    sync_status TEXT DEFAULT 'Pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    synced_at TEXT,
    last_error TEXT,
    FOREIGN KEY (learner_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS sync_queue (
    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER,
    queue_type TEXT NOT NULL,
    payload TEXT,
    sync_status TEXT DEFAULT 'Pending',
    attempts INTEGER DEFAULT 0,
    last_attempt_at TEXT,
    synced_at TEXT,
    error_message TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS offline_activity_logs (
    offline_log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    offline_status TEXT DEFAULT 'Recorded',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (actor_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS sync_events (
    sync_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    event_type TEXT NOT NULL,
    event_status TEXT NOT NULL,
    queued_count INTEGER DEFAULT 0,
    synced_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    details TEXT,
    attempted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (actor_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS cached_resources (
    cached_id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type TEXT NOT NULL,
    resource_id INTEGER,
    resource_title TEXT NOT NULL,
    cache_key TEXT UNIQUE NOT NULL,
    cache_status TEXT DEFAULT 'Cached',
    estimated_size_kb INTEGER DEFAULT 0,
    last_checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);



-- V8 dissertation-final proposal alignment tables
CREATE TABLE IF NOT EXISTS worked_examples (
    example_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id INTEGER NOT NULL,
    concept_tag TEXT NOT NULL,
    example_title TEXT NOT NULL,
    example_body TEXT NOT NULL,
    step_by_step_solution TEXT,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE IF NOT EXISTS practical_evidence (
    practical_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    subject_id INTEGER,
    topic_id INTEGER,
    outcome_id INTEGER NOT NULL,
    competency_id INTEGER,
    concept_id INTEGER,
    evidence_title TEXT NOT NULL,
    evidence_description TEXT,
    file_path TEXT,
    file_type TEXT,
    file_size_bytes INTEGER DEFAULT 0,
    teacher_status TEXT DEFAULT 'Pending Review',
    teacher_comment TEXT,
    rubric_level TEXT,
    rubric_score REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id),
    FOREIGN KEY (competency_id) REFERENCES competencies(competency_id),
    FOREIGN KEY (concept_id) REFERENCES concepts(concept_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE IF NOT EXISTS bkt_mastery (
    bkt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    concept_tag TEXT NOT NULL,
    prior_mastery_probability REAL DEFAULT 0.20,
    learn_probability REAL DEFAULT 0.12,
    guess_probability REAL DEFAULT 0.20,
    slip_probability REAL DEFAULT 0.10,
    probability_mastery REAL DEFAULT 0.20,
    current_mastery_probability REAL DEFAULT 0.20,
    confidence_score REAL DEFAULT 0,
    confidence REAL DEFAULT 0,
    observations INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    correct_attempts INTEGER DEFAULT 0,
    incorrect_attempts INTEGER DEFAULT 0,
    learning_gain REAL DEFAULT 0,
    time_spent_minutes INTEGER DEFAULT 0,
    predicted_mastery REAL DEFAULT 0,
    last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id),
    UNIQUE (learner_id, outcome_id, concept_tag)
);

CREATE TABLE IF NOT EXISTS system_settings (
    setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_key TEXT UNIQUE NOT NULL,
    setting_value TEXT NOT NULL,
    setting_description TEXT,
    setting_category TEXT DEFAULT 'General',
    setting_type TEXT DEFAULT 'text',
    updated_by INTEGER,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (updated_by) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS rubric_criteria (
    rubric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id INTEGER NOT NULL,
    criterion TEXT NOT NULL,
    description TEXT,
    level TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE IF NOT EXISTS rubric_assessments (
    assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    practical_id INTEGER NOT NULL,
    rubric_id INTEGER,
    teacher_id INTEGER NOT NULL,
    level TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    teacher_comment TEXT,
    assessed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (practical_id) REFERENCES practical_evidence(practical_id),
    FOREIGN KEY (rubric_id) REFERENCES rubric_criteria(rubric_id),
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS teacher_mastery_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    learner_id INTEGER NOT NULL,
    outcome_id INTEGER NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    teacher_comment TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (learner_id) REFERENCES users(user_id),
    FOREIGN KEY (outcome_id) REFERENCES learning_outcomes(outcome_id)
);

CREATE TABLE IF NOT EXISTS backups (
    backup_id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_name TEXT NOT NULL,
    backup_type TEXT DEFAULT 'manual',
    backup_status TEXT DEFAULT 'Recorded',
    file_path TEXT,
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS student_subject_assignments (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    assigned_by INTEGER,
    assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(user_id),
    FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
    FOREIGN KEY (assigned_by) REFERENCES users(user_id),
    UNIQUE (student_id, subject_id)
);

CREATE TABLE IF NOT EXISTS teacher_kb_uploads (
    upload_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_size_bytes INTEGER NOT NULL,
    summary_size_bytes INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (actor_id) REFERENCES users(user_id)
);

INSERT INTO roles (role_name, display_name) VALUES
('super_admin', 'Super Administrator'),
('school_admin', 'School Administrator'),
('teacher', 'Teacher'),
('learner', 'Learner');
INSERT INTO schools (school_name) VALUES ('Kigezi High School'), ('Kigata High School');
INSERT INTO subjects (subject_name) VALUES ('ICT'), ('Physics');
