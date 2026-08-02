"""The Phase 0 demo job — proves Celery → Redis → Channels → React end-to-end (§3.5)."""
import time

from celery import shared_task

from .publish import publish

FAKE_LOG = [
    "cloning repository…",
    "building image site:abc123…",
    "step 3/9: migrate — 2 migrations applied",
    "step 4/9: start green container on port 20001",
    "step 5/9: health check /healthz … ok (142 ms)",
    "step 7/9: caddy route switched",
    "step 8/9: smoke test https://demo.example.com … 200",
    "deploy complete ✔",
]


@shared_task
def demo_stream_logs(job_id, delay=0.5):
    topic = f"demo.{job_id}.log"
    for i, line in enumerate(FAKE_LOG):
        publish(topic, {"line": line, "n": i})
        time.sleep(delay)
    publish(topic, {"done": True, "n": len(FAKE_LOG)})
    return {"lines": len(FAKE_LOG)}
