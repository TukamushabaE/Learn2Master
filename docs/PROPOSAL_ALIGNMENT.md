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

## Framework Components

| Proposal component | Implemented module | Status |
|---|---|---|
| Learner Profiling Module | AI learner profile, learning pace, learning history, weak/strong concepts | Implemented |
| Sequential Content Adaptation Engine | Locked learning outcomes, post-test lock rules, next outcome unlock only after mastery | Implemented |
| Assessment and Feedback Module | Pre-test, adaptive practice, post-test, concept tagging, immediate feedback records | Implemented |
| Recommendation System | Adaptive notes, videos, weak-concept practice, explainable recommendations | Implemented |
| Explainable AI | AI explanations stored with evidence used, recommendation reason, confidence score | Implemented |
| Teacher Support Dashboard | Review queues, approve/override actions, interventions, learner detail and portfolios | Implemented |
| Evaluation Analytics | Mastery rate, learning gain, teacher actions, AI confidence and evidence completion | Implemented |
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
| Protect participant identity in dissertation reporting | Participant code, consent status, study phase, school/class/subject linkage | `research_participants`, `users`, `schools`, `classes`, `subjects` | `/research/participants` | Table 4.1 Participant Summary |
| Synthesize findings for discussion | Improved learning, mastery achieved, difficult concepts, AI contribution, teacher contribution, usability issues and limitations | Aggregated research dashboard helpers and operational evidence tables | `/research/chapter-five-insights` | Chapter Five Insights Page |
