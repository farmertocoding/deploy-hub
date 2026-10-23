FROM python:3.12-slim
WORKDIR /app
# pip 25.0.1 in python:3.12-slim vendors a certifi that still trusts the
# compromised emSign ECC Root CA - G3; 26.2.2 drops it. --hash is only legal
# inside a requirements file, so the pin goes through a one-line file.
RUN printf 'pip==26.2.2 --hash=sha256:fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70\n' > /tmp/pip.txt \
    && pip install --no-cache-dir --require-hashes -r /tmp/pip.txt \
    && rm /tmp/pip.txt
COPY requirements.txt .
RUN pip install --require-hashes --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "serve.py"]
