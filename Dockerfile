# Hub image — dev-grade for Phase 0. Digest pinning + Trivy gate (§6.8 supply
# chain) applies to *generated site images* now and to this image before Phase 2 exit.
FROM python:3.12-slim

ARG HUB_BUILD_ID=
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV HUB_BUILD_ID=${HUB_BUILD_ID}
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m hub \
    && mkdir -p /etc/deploy-hub \
    && chown hub:hub /app /etc/deploy-hub
COPY --chown=hub:hub . .
USER hub
ENTRYPOINT ["python", "-m", "vault.ensure_keyfile", "--"]
