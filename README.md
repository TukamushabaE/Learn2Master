# Learn2Master V8 — Final Dissertation Edition

AI-enabled Information System prototype for mastery-based learning under Uganda CBC, aligned to the MSc proposal: **An AI-Enabled Framework for Mastery-Based Learning under CBC**.

## Run

```bash
pip install -r requirements.txt
python init_db.py
python seed_data.py
python app.py
```

Open: `http://127.0.0.1:5000`

## Default accounts

Check `seed_data.py` for seeded usernames/passwords. Common demo accounts in recent builds are:

- Student: `elijah` / `12345`
- Teacher: `teacher` / `12345`
- Admin: `admin` / `12345`

## V8 proposal-aligned modules

- Authentication and role-based access
- Student, Teacher, Admin dashboards
- CBC learning pathway for Physics and ICT prototype topics
- Sequential learning outcome locking/unlocking
- Pre-test, adaptive practice, reflection, practical evidence, post-test
- Evidence-based mastery engine
- Adaptive notes, videos, worked examples and concept-based questions
- Simplified Bayesian Knowledge Tracing engine
- Explainable AI recommendation logging
- Teacher decision support: approve/override recommendations and review practical evidence
- Admin information system: users, schools, curriculum, questions, settings, reports, audit/offline logs
- Research dashboard for Chapter Four metrics
- Offline-ready foundation using SQLite, service worker and sync queue

## Documentation

See the `docs/` folder, especially:

- `V8_INCLUDED_MISSING_FEATURES.md`
- `V8_FINAL_ALIGNMENT.md`
- `FINAL_PROPOSAL_ALIGNMENT.md`
- `PROPOSAL_ALIGNMENT.md`
"# Learn2Master" 
