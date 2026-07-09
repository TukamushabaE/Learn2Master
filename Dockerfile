FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN adduser --disabled-password --gecos "" appuser && \
    mkdir -p /app/instance /app/logs /app/migrations && \
    chown -R appuser:appuser /app

USER appuser

COPY --chown=appuser:appuser . .

# Database initialization is handled by app.py at runtime

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5000/health || false

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:app"]
