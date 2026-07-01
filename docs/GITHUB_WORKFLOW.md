# GitHub Workflow

Use this workflow when you want to publish Learn2Master changes from VS Code or PowerShell.

## Check Local Changes

```powershell
git status
```

Review changed files before staging. Do not commit local databases, caches, uploads, virtual environments, or test scratch folders.

## Run Verification

```powershell
python init_db.py
python seed_data.py
python -m compileall routes services tests app.py seed_data.py
python -m pytest -q --basetemp .tmp_pytest -p no:cacheprovider
```

## Stage and Commit

```powershell
git add .
git status
git commit -m "Improve proposal alignment and research dashboards"
```

## Push to GitHub

```powershell
git push
```

## Pull Before New Work

```powershell
git pull origin main
```

If Git reports conflicts, resolve the listed files, run the verification commands again, then commit the conflict resolution.
