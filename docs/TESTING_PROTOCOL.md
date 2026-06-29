# Testing Protocol

Run database rebuild:

```powershell
python init_db.py
python seed_data.py
```

Run compile check:

```powershell
python -m compileall .
```

Run tests with a project-local pytest temp folder:

```powershell
python -m pytest -q --basetemp .tmp_pytest -p no:cacheprovider
```

Manual smoke checks:

- login as `elijah / 12345`
- login as `teacher / 12345`
- login as `admin / 12345`
- login as `superadmin / 12345`
- open learner portfolio and AI coach
- open teacher learner portfolio and practical evidence queue
- open admin users, roles, curriculum, settings, backups, reports and audit logs
- open research dashboard and CSV report

Expected core behavior:

- learner cannot access admin pages
- public registration creates learner only
- LO2 remains locked until LO1 is mastered
- post-test stays locked until pre-test, practice and reflection are complete
- practical outcomes require evidence before post-test unlock
- Super Admin can update global settings
- School Admin cannot update global settings
