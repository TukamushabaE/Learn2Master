FROM python:3.12-slim

WORKDIR /app

# Install system dependencies if any (none for now)

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure logs directory exists
RUN mkdir -p logs && chown -R 1000:1000 /app

# Switch to non-root user for security
USER 1000

EXPOSE 5000

# Entrypoint script to handle migrations and start gunicorn
CMD ["sh", "-c", "flask db upgrade && gunicorn --bind 0.0.0.0:5000 --workers 4 --access-logfile - --error-logfile - app:app"]
