FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Initialize database during build (not recommended for prod with real data, but fine for prototype)
RUN python seed_data.py

EXPOSE 5000

CMD ["python", "app.py"]
