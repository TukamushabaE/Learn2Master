# Learn2Master V8 Dissertation Final Edition

Learn2Master is an AI-enabled Flask information system with SQLite/PostgreSQL support for the MSc Information Systems dissertation:

**An AI-Enabled Framework for Mastery-Based Learning under CBC**

The system is aligned to Uganda Lower Secondary CBC principles and demonstrates learner profiling, sequential adaptive content, assessment and feedback, explainable recommendations, teacher decision support, offline readiness, evidence-based mastery and research analytics.

## Quick Start

```powershell
pip install -r requirements.txt
python manage.py init-db
$env:LEARN2MASTER_SEED_LEARNER_PASSWORD="ChooseLocalLearner123"
$env:LEARN2MASTER_SEED_TEACHER_PASSWORD="ChooseLocalTeacher123"
$env:LEARN2MASTER_SEED_SCHOOL_ADMIN_PASSWORD="ChooseLocalAdmin123"
$env:LEARN2MASTER_SEED_SUPER_ADMIN_PASSWORD="ChooseLocalSuper123"
python manage.py seed-demo-data
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Demo Accounts

The demo usernames are `elijah`, `teacher`, `admin`, and `superadmin`. Their passwords are the values you set in the `LEARN2MASTER_SEED_*_PASSWORD` environment variables before running `python manage.py seed-demo-data`.

For a production Supabase/PostgreSQL deployment, create real first users with:

```powershell
python manage.py create-initial-users
```

That command reads the first teacher, school administrator, and super administrator from `LEARN2MASTER_BOOTSTRAP_*`, `LEARN2MASTER_SUPER_ADMIN_*`, `LEARN2MASTER_SCHOOL_ADMIN_*`, and `LEARN2MASTER_TEACHER_*` environment variables.

## Core Modules

- Standard roles: Super Administrator, School Administrator, Teacher and Learner
- Admin user, role, school, curriculum, settings, backup, report and audit management
- CBC curriculum structure: subjects, terms, strands, sub-strands, topics, competencies, outcomes, indicators and success criteria
- Sequential mastery pathway: pre-test, adaptive content, reflection, practical evidence, practice, post-test and unlocks
- Evidence-based mastery engine with teacher review support
- Simplified Bayesian Knowledge Tracing for concept probability updates
- Explainable AI recommendation records and learner AI coach
- Practical evidence upload and rubric-based teacher review
- Learner and teacher competency portfolios
- Research dashboard with printable and CSV reports
- Chapter 4 and 5 evidence-readiness and writing guide
- Private Supabase Storage for teacher source documents with database-persisted AI summaries
- Offline foundation with sync queue, cached resources and service worker route
- Admin question-bank create/edit with concept, competency, Bloom level, difficulty and resource metadata
- Teacher pending-review queue, intervention history, learner detail review and teacher question creation
- Activity evidence submissions with teacher feedback

## Important Routes

- `/admin`
- `/admin/users`
- `/admin/roles`
- `/admin/curriculum`
- `/admin/settings`
- `/admin/ai-configuration`
- `/admin/backups`
- `/admin/question-bank`
- `/admin/learning-resources`
- `/admin/rubrics`
- `/admin/sync-logs`
- `/teacher`
- `/teacher/dashboard`
- `/teacher/learners`
- `/teacher/learner/<learner_id>`
- `/teacher/pending-reviews`
- `/teacher/interventions`
- `/teacher/question-bank`
- `/teacher/portfolio/<learner_id>`
- `/offline/status`
- `/offline/sync-queue`
- `/learner/ai-coach`
- `/learner/portfolio`
- `/ai/explanations`
- `/research/dashboard`
- `/research/chapter-guide`
- `/research/reports`
- `/research/export/csv`

## Verification

```powershell
python manage.py init-db
python manage.py seed-demo-data
python -m compileall routes services tests app.py seed_data.py
python -m pytest -q --basetemp .tmp_pytest -p no:cacheprovider
```

## Documentation

See `docs/` for proposal alignment, curriculum alignment, architecture, database dictionary, guides, testing protocol and demo script. Production Supabase and safe Render migration steps are in `docs/SUPABASE_SETUP.md`.

## GitHub Workflow

```powershell
git status
git add .
git commit -m "Improve proposal alignment and research dashboards"
git push
```

Do not commit local databases, caches, uploads, or virtual environments. They are excluded in `.gitignore`.
