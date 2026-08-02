# Hub image — dev-grade for Phase 0. Digest pinning + Trivy gate (§6.8 supply
# chain) applies to *generated site images* now and to this image before Phase 2 exit.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m hub && chown -R hub /app
USER hub
