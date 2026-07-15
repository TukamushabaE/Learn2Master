# Deployment Guide for Learn2Master

This guide provides instructions for deploying the Learn2Master AI-Enabled Mastery Learning System in a production environment.

## Infrastructure Requirements
- **Container Orchestration**: Docker on Render or another container host.
- **Database**: SQLite for local development and tests; Supabase PostgreSQL in production through `DATABASE_URL`.
- **Authentication**: Existing Flask authentication and role-based guards. Supabase Auth is not used.

## Environment Variables
The following variables should be set in production:

| Variable | Description | Required on Render |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string (Supabase or Render-managed) | Yes |
| `LEARN2MASTER_SECRET_KEY` | Flask signing key | Yes |
| `LEARN2MASTER_DEBUG` | Debug mode | Yes, set `0` |
| `LEARN2MASTER_FORCE_HTTPS` | HTTPS redirect control | Recommended `0` on Render unless ProxyFix is configured |
| `LEARN2MASTER_SESSION_COOKIE_SECURE` | Restrict session cookies to HTTPS | Set `1` on Render; use `0` only for local HTTP development |
| `LEARN2MASTER_CSRF_ENABLED` | CSRF protection | Yes, set `1` |
| `LEARN2MASTER_AUTO_SEED_DEMO` | Idempotently seed dissertation demo content on container start | Set `1` for the hosted demonstration only |
| `LEARN2MASTER_MAX_UPLOAD_BYTES` | Evidence upload size limit | Optional, e.g. `5242880` |
| `LEARN2MASTER_BOOTSTRAP_SCHOOL_NAME` | School created/used by bootstrap users | Yes for bootstrap |
| `LEARN2MASTER_SUPER_ADMIN_USERNAME` | First super admin username | Yes for bootstrap |
| `LEARN2MASTER_SUPER_ADMIN_EMAIL` | First super admin email | Yes for bootstrap |
| `LEARN2MASTER_SUPER_ADMIN_FULL_NAME` | First super admin full name | Yes for bootstrap |
| `LEARN2MASTER_SUPER_ADMIN_PASSWORD` | First super admin password | Yes for bootstrap |
| `LEARN2MASTER_SCHOOL_ADMIN_USERNAME` | First school admin username | Yes for bootstrap |
| `LEARN2MASTER_SCHOOL_ADMIN_EMAIL` | First school admin email | Yes for bootstrap |
| `LEARN2MASTER_SCHOOL_ADMIN_FULL_NAME` | First school admin full name | Yes for bootstrap |
| `LEARN2MASTER_SCHOOL_ADMIN_PASSWORD` | First school admin password | Yes for bootstrap |
| `LEARN2MASTER_TEACHER_USERNAME` | First teacher username | Yes for bootstrap |
| `LEARN2MASTER_TEACHER_EMAIL` | First teacher email | Yes for bootstrap |
| `LEARN2MASTER_TEACHER_FULL_NAME` | First teacher full name | Yes for bootstrap |
| `LEARN2MASTER_TEACHER_PASSWORD` | First teacher password | Yes for bootstrap |
| `PORT` | Application port | Render sets this automatically |

## Render Deployment (Recommended)
Learn2Master is optimized for Render as a single **Web Service**. You do not need a separate frontend deployment as Flask serves static assets via WhiteNoise. The included `render.yaml` creates the web service and a managed PostgreSQL database, generates the Flask signing key, and prompts for the four demo account passwords without storing them in Git.

### Blueprint deployment
1. Push this repository to GitHub.
2. In Render, choose **New > Blueprint** and connect the repository.
3. Enter secure, unique values for the four `LEARN2MASTER_SEED_*_PASSWORD` prompts.
4. Apply the Blueprint and wait for both resources to report **Live/Available**.
5. Open the service URL and verify `/health` returns `{"status":"healthy","database":"reachable"}`.

The free Render database is intended for dissertation demonstrations and expires after 30 days. Upgrade it or provide a Supabase `DATABASE_URL` for longer-lived production data.

### Configuration Settings:
- **Runtime**: `Python`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn --bind 0.0.0.0:$PORT --workers 4 app:app`

### Supabase Database Setup on Render (alternative):
1. Create a Supabase project.
2. Copy the PostgreSQL connection string from Supabase Database settings.
3. Add it to the Render Web Service as `DATABASE_URL`.
4. Do not configure Supabase Auth; Learn2Master uses its Flask login and roles.
5. Open the Render Shell and run:
   ```bash
   python manage.py init-db
   flask db upgrade
   python manage.py create-initial-users
   ```
6. Optional demo CBC content for dissertation demonstration:
   ```bash
   python manage.py seed-demo-data
   ```

`python manage.py init-db` and `flask db upgrade` are idempotent. They do not drop existing Supabase data. Use `--reset` only against a local development database.

## Docker Deployment
1. Build the image:
   ```bash
   docker build -t learn2master:latest .
   ```
2. Run the container:
   ```bash
   docker run -d -p 5000:5000 \
     -e SECRET_KEY="your-secure-key" \
     -v learn2master_data:/app/instance \
     learn2master:latest
   ```

## Database Migrations
If you modify the database schema (`models.py` or `database_v2.sql`), use the following commands:

1. Generate a new migration:
   ```bash
   flask db migrate -m "Description of change"
   ```
2. Apply migrations:
   ```bash
   flask db upgrade
   ```

For first deployment or after pulling schema changes:

```bash
python manage.py init-db
flask db upgrade
```

## Monitoring & Health
- **Health Endpoint**: `GET /health` returns `{"status": "healthy"}`.
- **Logs**: Application logs are stored in `logs/learn2master.log` with automatic rotation.
- **Docker Healthcheck**: Included in the Dockerfile; monitors the `/health` endpoint every 30s.

## Security Features
- **Rate Limiting**: Brute-force protection on Login (5 req/min) and Assessment (10 req/min).
- **Security Headers**: HSTS, CSP, and XSS protection enabled via Talisman.
- **Static Assets**: Served efficiently via WhiteNoise with compression support.
