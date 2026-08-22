# sample-site

Minimal Django/ASGI fixture for deploy-hub (D-030). Serves pinned `/healthz`
JSON `{live, ready, checks}`. Set `DELAYED_READY_S` to hold `ready` false for
that many seconds after start.

No secrets. Dependencies are hash-pinned in `requirements.txt`. Image install
is `pip install --require-hashes`.
