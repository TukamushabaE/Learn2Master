FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root user and the instance directory early
RUN adduser --disabled-password --gecos "" appuser &&     mkdir -p /app/instance &&     mkdir -p /app/logs &&     chown -R appuser:appuser /app

USER appuser

COPY --chown=appuser:appuser . .

RUN python seed_data.py

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:app"]
