# System Architecture

Learn2Master is a Flask and SQLite prototype organized around blueprints and small service modules.

Main blueprints:

- `auth`: login, registration, password change and authentication audit.
- `student`: learner dashboard, analytics and competency portfolio.
- `learning`: sequential mastery pathway, assessment submission, reflection and practical evidence.
- `teacher`: teacher dashboard, AI review, practical evidence review and learner portfolio.
- `admin`: schools, users, roles, curriculum, settings, reports, backups and audit logs.
- `research`: dissertation dashboard, printable reports and CSV export.
- `ai`: learner AI coach and explainable AI records.

Core services:

- `mastery_engine.py`: evidence-based mastery decision.
- `bkt_engine.py`: simplified Bayesian Knowledge Tracing.
- `recommendation_engine.py`: explainable adaptive recommendations.
- `evidence_engine.py`: reflection/evidence helpers and AI explanations.
- `analytics_engine.py`: computed dashboard indicators.

The prototype uses SQLite for repeatable dissertation demonstration, with `init_db.py` creating tables from `database_v2.sql` and `seed_data.py` loading the CBC starter dataset.
