"""SEC-B4: Redis stays compose-internal with requirepass; Celery is JSON-only.

C9: this is a compose parse (and settings pin), not an external port-scan.
The §6B Hub port-scan of Redis-from-outside remains a later activity; the
waiver retired when these tests started reading docker-compose.yml.
"""
import pathlib

import pytest
import yaml
from django.conf import settings

REPO = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = REPO / "docker-compose.yml"

pytestmark = pytest.mark.req("SEC-B4-REDIS-CROWN-JEWEL")


def _compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _command_tokens(command):
    if command is None:
        return []
    if isinstance(command, str):
        return command.split()
    return list(command)


def test_compose_redis_unpublished_and_requirepass():
    """Redis has no published port and requirepass is set.

    What would make this fail: a `ports:` stanza on the redis service (even
    bound to 127.0.0.1), host networking, or dropping `--requirepass`.
    """
    redis = _compose()["services"]["redis"]
    assert redis.get("ports") in (None, [], {}), (
        f"redis publishes ports {redis.get('ports')!r} — §B4 is compose-internal only"
    )
    assert redis.get("network_mode") not in {"host", "service:host"}, (
        "redis on host networking is a published Redis"
    )
    networks = redis.get("networks") or []
    assert "internal" in networks, f"redis networks={networks!r} must include internal"

    tokens = _command_tokens(redis.get("command"))
    assert "--requirepass" in tokens, f"redis command {tokens!r} missing --requirepass"
    idx = tokens.index("--requirepass")
    assert idx + 1 < len(tokens) and str(tokens[idx + 1]).strip(), (
        "requirepass is present but its password argument is empty"
    )


def test_celery_serializers_are_json():
    """Celery serializers are pinned to JSON (never pickle).

    What would make this fail: CELERY_TASK_SERIALIZER / RESULT_SERIALIZER /
    ACCEPT_CONTENT accepting pickle, or a compose env that overrides them.
    """
    assert settings.CELERY_TASK_SERIALIZER == "json"
    assert settings.CELERY_RESULT_SERIALIZER == "json"
    assert list(settings.CELERY_ACCEPT_CONTENT) == ["json"]

    for service in _compose()["services"].values():
        env = service.get("environment") or {}
        if isinstance(env, list):
            env = dict(item.split("=", 1) for item in env if "=" in item)
        for key in (
            "CELERY_TASK_SERIALIZER",
            "CELERY_RESULT_SERIALIZER",
            "CELERY_ACCEPT_CONTENT",
        ):
            if key in env:
                assert "json" in str(env[key]).lower()
                assert "pickle" not in str(env[key]).lower(), (
                    f"compose {key}={env[key]!r} reopens pickle on the broker"
                )
