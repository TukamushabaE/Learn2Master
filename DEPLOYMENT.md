# Deployment Guide for Learn2Master

This guide provides instructions for deploying the Learn2Master AI-Enabled Mastery Learning System in a production environment.

## Infrastructure Requirements
- **Container Orchestration**: Docker and Docker Compose (or Kubernetes).
- **Database**: SQLite (default, stored in `instance/`) or a production SQL database (PostgreSQL/MySQL) via `DATABASE_URL`.
- **Reverse Proxy**: Nginx or Traefik recommended to handle SSL termination (though `Flask-Talisman` handles HSTS/Security headers).

## Environment Variables
The following variables should be set in production:

| Variable | Description | Recommended Value |
| --- | --- | --- |
| `SECRET_KEY` | Flask security key | A long, random string. |
| `DATABASE_URL` | DB connection string | `postgresql://user:pass@host/db` |
| `FLASK_DEBUG` | Debug mode | `False` |
| `PORT` | Application port | `5000` |

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
If you modify the database schema (`models.py`), use the following commands to manage migrations:

1. Generate a new migration:
   ```bash
   docker exec -it <container_id> flask db migrate -m "Description of change"
   ```
2. Apply migrations:
   ```bash
   docker exec -it <container_id> flask db upgrade
   ```

## Monitoring & Health
- **Health Endpoint**: `GET /health` returns `{"status": "healthy"}`.
- **Logs**: Application logs are stored in `logs/learn2master.log` with automatic rotation.
- **Docker Healthcheck**: Included in the Dockerfile; monitors the `/health` endpoint every 30s.

## Security Features
- **Rate Limiting**: Brute-force protection on Login (5 req/min) and Assessment (10 req/min).
- **Security Headers**: HSTS, CSP, and XSS protection enabled via Talisman.
- **Static Assets**: Served efficiently via WhiteNoise with compression support.
