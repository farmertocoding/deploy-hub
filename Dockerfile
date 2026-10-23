# Hub image — dev-grade for Phase 0. Digest pinning + Trivy gate (§6.8 supply
# chain) applies to *generated site images* now and to this image before Phase 2 exit.
FROM python:3.12-slim

ARG HUB_BUILD_ID=
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV HUB_BUILD_ID=${HUB_BUILD_ID}
WORKDIR /app

# pip 25.0.1 in python:3.12-slim vendors a certifi that still trusts the
# compromised emSign ECC Root CA - G3; 26.2.2 drops it. --hash is only legal
# inside a requirements file, so the pin goes through a one-line file.
RUN printf 'pip==26.2.2 --hash=sha256:fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70\n' > /tmp/pip.txt \
    && pip install --no-cache-dir --require-hashes -r /tmp/pip.txt \
    && rm /tmp/pip.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m hub \
    && mkdir -p /etc/deploy-hub \
    && chown hub:hub /app /etc/deploy-hub
COPY --chown=hub:hub . .
USER hub
ENTRYPOINT ["python", "-m", "vault.ensure_keyfile", "--"]
