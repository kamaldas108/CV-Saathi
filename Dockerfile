# CV-Saathi on Google Cloud Run.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cvsaathi ./cvsaathi
COPY web ./web

# Cloud Run sets $PORT and terminates HTTPS in front of the container; --proxy-headers
# lets the app see the https scheme (secure cookies, wss:// for the voice connection).
CMD exec uvicorn cvsaathi.server:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips="*"
