FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements*.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY app.py .
USER 10001:10001
CMD ["gunicorn", "--bind=0.0.0.0:8080", "--workers=2", "--worker-class=gthread", "--threads=4", "--timeout=30", "--keep-alive=5", "app:app"]
