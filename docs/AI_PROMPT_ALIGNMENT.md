# AI Prompt Alignment Update

Source: `C:\Advanced OOP\New REC files\AI prompt.pdf`

This update moves Learn2Master closer to the requested production-quality dissertation prototype while preserving the existing working Flask flow.

## Implemented in this pass

- Replaced the legacy role model with the four prompt-approved roles:
  - Super Administrator
  - School Administrator
  - Teacher
  - Learner
- Public registration now creates only Learner accounts.
- Added normalized curriculum and AI evidence tables:
  - topics
  - concepts
  - learning_resources
  - teacher_feedback
- Expanded existing tables:
  - roles now store display names.
  - courses can link to topics.
  - questions store Bloom level, explanation, feedback, resource hints and estimated time.
  - recommendations store evidence used, weak concepts, strong concepts, confidence, expected mastery, study time and recommended resource.
  - learner_profiles store weak concepts, strong concepts, confidence score, mastery score, predicted performance and learning gain.
  - bkt_mastery stores confidence, learning gain, time spent and predicted mastery.
- Seed data now creates:
  - one ICT topic and one Physics topic.
  - 12 concept records.
  - 36 learning resource records from notes, videos and worked examples.
  - demo accounts for all four approved roles.
- Learner-facing pages now show richer explainable AI and BKT evidence.
- Admin question-bank pages now expose question metadata required by the prompt.

## Demo accounts

- Learner: `elijah` / `12345`
- Teacher: `teacher` / `12345`
- School Administrator: `admin` / `12345`
- Super Administrator: `superadmin` / `12345`

## Remaining larger work

The prompt also asks for full production-grade management workflows for backups, AI configuration, resource uploads, simulations, dark mode, dashboards, and every listed activity type. The current update lays the database and route foundation for those features without destabilizing the working mastery-learning prototype.
