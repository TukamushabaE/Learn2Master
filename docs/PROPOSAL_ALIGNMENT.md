# Learn2Master V8 Dissertation Release - Proposal Alignment

Research title: **An AI-Enabled Framework for Mastery-Based Learning under CBC**

## Current Implementation Trace

- Learner profiling: `learner_profiles`, `/profile`, `/learner/portfolio`.
- Sequential content adaptation: `/pathway/<course_id>`, `/outcome/<outcome_id>`.
- Assessment and feedback: `assessments`, `assessment_attempts`, `teacher_feedback`.
- Recommendation system: `recommendations`, `ai_explanations`, `/learner/ai-coach`, `/teacher/ai-insights`, `/admin/ai-configuration`.
- Teacher support dashboard: `/teacher/dashboard`, `/teacher/pending-reviews`, `/teacher/interventions`, `/teacher/learner/<id>`, `/teacher/portfolio/<learner_id>`.
- Offline/resource optimization: `sync_queue`, `offline_sync_queue`, `cached_resources`, `offline_activity_logs`, `sync_events`, `/offline/status`, `/offline/sync-queue`, `/admin/sync-logs`.
- Explainable AI: `ai_explanations`, `/ai/explanations`.
- Evaluation analytics: `/research/dashboard`, `/research/reports`, `/research/export/csv`.
- Research and evaluation module: `/research/participants`, `/research/pre-post-results`, `/research/learning-gain`, `/research/mastery-attainment`, `/research/teacher-oversight`, `/research/questionnaires`, `/research/questionnaire-results`, `/research/system-logs`, `/research/chapter-four-report`, `/research/chapter-five-insights`.
- Evaluation-readiness controls: `/research/feedback-responsiveness`, `/research/system-reliability`, `/research/data-integrity`, `/research/data-collection-readiness`, and `/research/proposal-traceability`.
- Ethical research gating: learner analytics, questionnaire summaries, and research exports include only active participants with granted consent/assent requirements; reports use participant codes rather than names or user IDs.
- Assessment timing and reliability evidence: `assessment_attempts.started_at`, `completed_at`, `time_spent_seconds`, `sync_events`, failed queues, and `/research/system-logs`.

## Framework Components

| Proposal component | Implemented module | Status |
|---|---|---|
| Learner Profiling Module | AI learner profile, learning pace, learning history, weak/strong concepts | Implemented |
| Sequential Content Adaptation Engine | Locked learning outcomes, post-test lock rules, next outcome unlock only after mastery | Implemented |
| Assessment and Feedback Module | Pre-test, adaptive practice, post-test, concept tagging, immediate feedback records | Implemented |
| Recommendation System | Adaptive notes, videos, weak-concept practice, explainable recommendations | Implemented |
| Explainable AI | AI explanations stored with evidence used, recommendation reason, confidence score | Implemented |
| Teacher Support Dashboard | Review queues, approve/override actions, interventions, learner detail and portfolios | Implemented |
| Evaluation Analytics | Pre/post timing, mastery rate, learning gain charts, teacher actions, AI confidence, evidence completion, and reliability summaries | Implemented |
| Offline / Low-resource Layer | Cache register, sync queue, sync events and admin sync logs | Prototype foundation implemented |
| CBC Evidence of Mastery | Reflection, practice, practical evidence, activity submissions and rubric review | Implemented |
| Question Intelligence | Metadata-rich question bank with concept, competency, Bloom level, type and difficulty | Implemented |

## Mastery Rule

A learner cannot move from one learning outcome to the next until the required evidence is complete:

1. Pre-test completed.
2. Adaptive practice completed.
3. Weak concepts resolved.
4. CBC reflection submitted.
5. Practical evidence submitted where the outcome requires it.
6. Post-test passed at the threshold.
7. Evidence-based mastery decision equals `Mastered`, with teacher review where required.

## Demonstration Flow

Learner login -> Subjects -> Pathway -> LO1 -> Pre-test -> Adaptive notes/videos/examples -> CBC activity evidence -> Practice -> Reflection -> Post-test -> Evidence-based mastery -> LO2 unlock.

Teacher login -> Dashboard -> Pending reviews -> Review evidence or AI recommendations -> Approve, reject, request revision, override or assign remediation -> Intervention is recorded.

Admin login -> Users/curriculum/question bank/AI configuration/offline sync logs/research dashboard -> Export report evidence for dissertation analysis.

## Research Evaluation Traceability

| Research Objective | Evaluation Indicator | System Data Source | System Route | Chapter Four Output |
|---|---|---|---|---|
| Evaluate learner improvement under mastery-based learning | Pre-test score, post-test score, learning gain, normalized gain | `assessment_attempts`, `assessments`, `mastery_records` | `/research/pre-post-results`, `/research/learning-gain` | Table 4.2 Pre-test Results, Table 4.3 Post-test Results, Table 4.4 Learning Gain |
| Determine mastery attainment under CBC | Mastered, in progress, remediation required, attempts to mastery, time-to-mastery | `mastery_records`, `assessment_attempts`, `learning_outcomes` | `/research/mastery-attainment` | Table 4.5 Mastery Attainment |
| Assess teacher oversight and decision support | Teacher approval, override, remediation, feedback, practical evidence review, reopen decisions | `teacher_mastery_reviews`, `teacher_feedback`, `teacher_interventions`, `practical_evidence` | `/research/teacher-oversight` | Table 4.6 Teacher Oversight |
| Evaluate learner and teacher user acceptance | Likert constructs for usefulness, ease of use, feedback usefulness, engagement, satisfaction, AI clarity, CBC alignment and trust | `research_questionnaires`, `research_questionnaire_items`, `research_questionnaire_responses`, `research_questionnaire_answers` | `/research/questionnaires`, `/research/questionnaire-results` | Table 4.7 User Acceptance |
| Track system usage and reliability evidence | Login/logout, subject opened, learning outcome opened, resource viewed, assessment submission, recommendation generation, teacher feedback, export generated | `audit_logs`, `activity_logs` | `/research/system-logs` | Table 4.8 System Usage |
| Evaluate operation under intermittent connectivity | Sync success rate, failed synchronization items, pending queue items, recorded incidents | `sync_events`, `offline_sync_queue`, `sync_queue` | `/research/system-logs`, `/research/dashboard` | Table 4.8 System Usage and Reliability |
| Protect participant identity in dissertation reporting | Participant code, consent status, study phase, school/class/subject linkage | `research_participants`, `users`, `schools`, `classes`, `subjects` | `/research/participants` | Table 4.1 Participant Summary |
| Synthesize findings for discussion | Improved learning, mastery achieved, difficult concepts, AI contribution, teacher contribution, usability issues and limitations | Aggregated research dashboard helpers and operational evidence tables | `/research/chapter-five-insights` | Chapter Five Insights Page |

## Proposal-to-system traceability matrix

| Research question / objective | DSRM stage | Operational measure | Database or event evidence | Application evidence | Chapter 4 reporting | Chapter 5 interpretation | Status / boundary |
|---|---|---|---|---|---|---|---|
| RQ1 / Objective 1: represent CBC outcomes as a mastery sequence | Design and development | Ordered outcomes and prerequisite rules | `subjects`, `competencies`, `learning_outcomes`, `lessons` | `/admin/subjects`, `/pathway/<course_id>` | Curriculum configuration | Design interpretation | Implemented; verify actual study curriculum before collection |
| RQ2 / Objective 2: adapt feedback to diagnosed weakness | Demonstration | Recommendation generated, viewed and followed | `assessment_attempts`, `recommendations`, `research_events` | `/research/feedback-responsiveness` | Feedback-response table | Cautious adaptive-feedback interpretation | Followed requires a later practice/post-test submission |
| RQ3 / Objective 3: evaluate learning gain and mastery | Evaluation | Valid paired pre/post, normalized gain, mastery status and time | `assessment_attempts`, `mastery_records` | `/research/learning-gain`, `/research/mastery-attainment` | Paired outcomes and mastery tables | Outcome interpretation | Pairing never crosses learner, outcome or phase |
| RQ4 / Objective 4: evaluate teacher oversight | Evaluation | Intervention, review, approval, override and response time | `teacher_interventions`, `teacher_feedback`, `teacher_mastery_reviews`, `practical_evidence` | `/research/teacher-oversight` | Oversight table | Teacher contribution interpretation | Implemented; empty evidence remains “No data yet” |
| RQ5 / Objective 5: assess acceptance and dependable operation | Evaluation and communication | Likert responses and recorded success/failure timings | `research_questionnaire_*`, `research_events`, sync tables | `/research/questionnaire-results`, `/research/system-reliability` | Questionnaire and reliability tables | Usability, operation and limitation interpretation | Reliability is recorded application evidence, not external uptime |

The same matrix is available in the authorized application at `/research/proposal-traceability`. Data-collection controls and analytic boundaries are documented in `docs/DATA_COLLECTION_READINESS.md`.
