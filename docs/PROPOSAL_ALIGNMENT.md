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
