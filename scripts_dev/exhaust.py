"""SEC-69 exhaust scanner: vault plaintext in pytest capture and Celery kwargs.

Not `make log-scrub`. That target greps source files for `SECRET_KEY\\s*=`.
This is the gate the requirement names: captured pytest stdout/stderr/log
and Celery task args/kwargs. The leak message never echoes the secret.
"""
from __future__ import annotations

VAULT_PLAINTEXT_MARKER = "VAULT-TEST-PLAINTEXT-MARKER"

_CELERY_WRAPPED = False


class ExhaustLeak(AssertionError):
    """A vault plaintext marker reached exhaust. The message names the surface."""


def _as_text(obj):
    if obj is None:
        return ""
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj).decode("utf-8", "replace")
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        parts = []
        for key, value in obj.items():
            parts.append(_as_text(key))
            parts.append(_as_text(value))
        return "\n".join(parts)
    if isinstance(obj, (list, tuple, set, frozenset)):
        return "\n".join(_as_text(item) for item in obj)
    return str(obj)


def _contains_marker(text):
    return VAULT_PLAINTEXT_MARKER in (text or "")


def captured_leaks(*, stdout="", stderr="", log=""):
    """Return the capture streams that carry the vault plaintext marker."""
    hits = []
    if _contains_marker(stdout):
        hits.append("stdout")
    if _contains_marker(stderr):
        hits.append("stderr")
    if _contains_marker(log):
        hits.append("log")
    return hits


def celery_kwargs_leaks(args=None, kwargs=None):
    """True if Celery args/kwargs carry the vault plaintext marker."""
    return _contains_marker(_as_text(args) + "\n" + _as_text(kwargs))


def scan_report_captures(report):
    return captured_leaks(
        stdout=getattr(report, "capstdout", "") or "",
        stderr=getattr(report, "capstderr", "") or "",
        log=getattr(report, "caplog", "") or "",
    )


def install_celery_wrap():
    """Wrap Task.apply_async / Celery.send_task so a leak fails closed."""
    global _CELERY_WRAPPED
    if _CELERY_WRAPPED:
        return
    from celery.app.base import Celery
    from celery.app.task import Task

    original_apply = Task.apply_async
    original_send = Celery.send_task

    def apply_async(self, args=None, kwargs=None, *rest, **options):
        if celery_kwargs_leaks(args, kwargs):
            raise ExhaustLeak("Celery task kwargs")
        return original_apply(self, args, kwargs, *rest, **options)

    def send_task(self, name, args=None, kwargs=None, *rest, **options):
        if celery_kwargs_leaks(args, kwargs):
            raise ExhaustLeak("Celery send_task kwargs")
        return original_send(self, name, args, kwargs, *rest, **options)

    Task.apply_async = apply_async
    Celery.send_task = send_task
    _CELERY_WRAPPED = True
