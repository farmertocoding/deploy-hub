"""ImageRegistry port + ensure_ship flip (D-073 / AWS-IMAGE-REGISTRY).

boto3, botocore, and moto must not appear as imports in this file. A real
ECR client, if one lands, lives in providers/image_registry.py so the
tested constructor is the shipped one (D-073).
"""
import ast
import pathlib
import re
from types import SimpleNamespace

import pytest
from test_ensure_build import GIT_SHA, StepTransport

REPO = pathlib.Path(__file__).resolve().parent.parent
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)
ARCHIVE = b"fake-image-archive-not-a-secret"
NAV_IDS = ["home", "sites", "targets", "deploys", "findings", "settings"]


class ShipTransport(StepTransport):
    """Load or pull of the inspected tag makes a later inspect a hit."""

    def run(self, argv, *, timeout=60):
        result = super().run(argv, timeout=timeout)
        argv = list(argv)
        if argv and argv[0] == "docker" and "pull" in argv:
            pending = getattr(self, "_last_inspect_miss", None)
            if pending:
                self.images.add(pending)
        if argv[:2] == ["docker", "tag"] and len(argv) >= 4:
            self.images.add(argv[-1])
        return result


def _desired(transport, *, body=None, registry=None, target=None, extra=None):
    desired = {
        "transport": transport,
        "git_sha": GIT_SHA,
        "manifest_body": body if body is not None else {"runtime": "node"},
        "image_archive": ARCHIVE,
    }
    if registry is not None:
        desired["registry"] = registry
    if target is not None:
        desired["target"] = target
    if extra:
        desired.update(extra)
    return desired


def _argv_tokens(transport):
    tokens = []
    for kind, payload in transport.calls:
        if kind in ("run", "probe") and isinstance(payload, list):
            tokens.extend(str(part) for part in payload)
    return tokens


def _runs(transport, *needles):
    found = []
    for kind, argv in transport.calls:
        if kind != "run" or not isinstance(argv, list):
            continue
        blob = " ".join(str(part) for part in argv)
        if all(needle in argv or needle in blob for needle in needles):
            found.append(argv)
    return found


@pytest.mark.req("AWS-IMAGE-REGISTRY")
def test_ensure_ship_none_still_docker_loads():
    """registry is None (default ship_mode load) still docker-loads on miss.

    What would make this fail: treating an absent registry as a constructed
    open registry, or flipping the default to docker pull so sites without
    ship_mode: registry stop loading.
    """
    from deploys.steps import ensure_ship, image_tag

    transport = ShipTransport()
    desired = _desired(transport)
    tag = image_tag(GIT_SHA, desired["manifest_body"])
    result = ensure_ship(desired)

    assert desired.get("registry") is None
    assert (desired.get("manifest_body") or {}).get("ship_mode") in (None, "load")
    loads = _runs(transport, "docker", "load")
    assert loads, transport.calls
    assert not _runs(transport, "pull")
    assert result["status"] == "shipped"
    assert result["tag"] == tag


@pytest.mark.req("AWS-IMAGE-REGISTRY")
def test_ensure_ship_with_registry_pushes_and_pulls():
    """A registry port pushes the archive then the target pulls with pull-only cred.

    Login is a 0600 cred file or stdin — never --password on argv. docker load
    is not the registry path.

    What would make this fail: docker load despite desired['registry'],
    docker login --password SECRET, or pushing with the pull cred.
    """
    from deploys.steps import ensure_ship, image_tag
    from providers.fakes import FakeImageRegistry

    transport = ShipTransport()
    registry = FakeImageRegistry()
    target = SimpleNamespace(pk=11)
    desired = _desired(transport, registry=registry, target=target)
    tag = image_tag(GIT_SHA, desired["manifest_body"])

    result = ensure_ship(desired)

    assert registry.mutating_calls()
    assert any(call[0] == "push" and call[1] == tag for call in registry.calls)
    assert registry.images[tag] == ARCHIVE
    assert not _runs(transport, "docker", "load")
    pulls = _runs(transport, "pull")
    assert pulls, transport.calls
    spec = registry.pull_spec(tag, target=target)
    tokens = _argv_tokens(transport)
    assert spec["password"] not in tokens
    assert spec["username"] != registry.push_username
    assert spec["password"] != registry.push_password
    assert "--password" not in tokens
    cred_puts = [
        remote for remote, mode in transport.put_modes.items() if mode == 0o600
    ]
    assert cred_puts, transport.put_modes
    assert result["status"] == "shipped"
    assert result["tag"] == tag


@pytest.mark.req("AWS-IMAGE-REGISTRY")
def test_fake_registry_requires_tls_and_auth():
    """FakeImageRegistry is not constructible open: TLS and auth are required.

    What would make this fail: a default Fake that serves http or anonymous
    push, so a push-open Fake is a green test.
    """
    from providers.fakes import FakeImageRegistry

    with pytest.raises((TypeError, ValueError, RuntimeError), match="tls|TLS|https"):
        FakeImageRegistry(tls=False)
    with pytest.raises((TypeError, ValueError, RuntimeError), match="auth|Auth"):
        FakeImageRegistry(auth=False)
    with pytest.raises((TypeError, ValueError, RuntimeError), match="tls|TLS|https"):
        FakeImageRegistry(url="http://registry.test")
    with pytest.raises((TypeError, ValueError, RuntimeError), match="auth|Auth|password"):
        FakeImageRegistry(push_password="")

    registry = FakeImageRegistry()
    assert {"tls", "auth"} <= set(registry.capabilities())
    assert str(registry.url).startswith("https://")


@pytest.mark.req("AWS-IMAGE-REGISTRY")
def test_push_cred_is_not_pull_cred():
    """Hub push credentials are never the per-target pull-only pair.

    What would make this fail: pull_spec returning the Fake's push username
    or password, so a target can push.
    """
    from providers.fakes import FakeImageRegistry

    registry = FakeImageRegistry()
    registry.push("img", ARCHIVE)
    spec = registry.pull_spec("img", target=SimpleNamespace(pk=3))
    assert spec["username"] != registry.push_username
    assert spec["password"] != registry.push_password
    assert spec["url"]
    assert spec["username"]
    assert spec["password"]


@pytest.mark.req("AWS-IMAGE-REGISTRY")
def test_pull_cred_is_per_target():
    """Two targets receive distinct pull-only credentials for the same tag.

    What would make this fail: a single registry-wide pull user shared
    across targets.
    """
    from providers.fakes import FakeImageRegistry

    registry = FakeImageRegistry()
    registry.push("img", ARCHIVE)
    a = registry.pull_spec("img", target=SimpleNamespace(pk=21))
    b = registry.pull_spec("img", target=SimpleNamespace(pk=22))
    assert a["username"] != b["username"]
    assert a["password"] != b["password"]
    assert a["url"] == b["url"]
    assert a["username"] != registry.push_username
    assert b["username"] != registry.push_username


@pytest.mark.req("AWS-IMAGE-REGISTRY")
def test_image_registry_for_unconfigured_returns_none():
    """Default / unconfigured construction is None (docker load), not an open registry.

    What would make this fail: image_registry_for() returning a Fake or ECR
    client when ship_mode is omitted, so the default is no longer load.
    """
    from providers.fakes import FakeImageRegistry
    from providers.registry import image_registry_for

    assert image_registry_for() is None
    assert image_registry_for({}) is None
    assert image_registry_for({"manifest_body": {}}) is None
    assert image_registry_for({"ship_mode": "load"}) is None
    assert image_registry_for({"manifest_body": {"ship_mode": "load"}}) is None
    built = image_registry_for()
    assert built is None or not isinstance(built, FakeImageRegistry)


@pytest.mark.req("AWS-IMAGE-REGISTRY")
def test_image_registry_not_in_providers_registry_module_as_ecr_client():
    """providers/registry.py has image_registry_for; boto3/ECR clients stay out.

    What would make this fail: `import boto3` or boto3.client('ecr') in
    providers/registry.py, so D-073's tested-client split is gone.
    """
    import inspect

    import providers.registry as registry_mod
    from providers.registry import image_registry_for

    assert callable(image_registry_for)
    assert getattr(registry_mod, "boto3", None) is None
    path = REPO / "providers" / "registry.py"
    text = path.read_text(encoding="utf-8")
    compact = text.replace(" ", "").replace('"', "'")
    assert "client('ecr'" not in compact
    tree = ast.parse(text)
    forbidden = {"boto3", "botocore", "moto"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden
    source = inspect.getsource(image_registry_for)
    assert "boto3" not in source
    assert "botocore" not in source
    assert "moto" not in source
    assert "client(" not in source


def test_nav_still_six():
    """Image shipping is a ship_mode flip, not a 7th NAV item.

    What would make this fail: adding Registry/Cloud/Instances as a 7th
    NAV entry.
    """
    src = (REPO / "frontend" / "src" / "Chrome.jsx").read_text(encoding="utf-8")
    start = src.index("export const NAV = [")
    end = src.index("];", start)
    ids = re.findall(r'id:\s*"(\w+)"', src[start:end])
    assert ids == NAV_IDS


def test_image_registry_tests_do_not_import_boto3():
    """This module and tests/ never import boto3/moto.

    What would make this fail: a convenience `import boto3` here, so the
    tested client is no longer the shipped providers/image_registry helper.
    """
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(text) is None
    offenders = []
    for py in (REPO / "tests").rglob("*.py"):
        if _IMPORT_BOTO.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py.relative_to(REPO)))
    assert offenders == [], f"boto3/botocore/moto import in tests/: {offenders}"


@pytest.mark.req("AWS-IMAGE-REGISTRY")
def test_ensure_ship_run_twice_zero_mutating_calls():
    """Second registry ship is inspect-only: no push, pull, put, or load.

    What would make this fail: inspect via run, or a second push/pull/put
    after the image is already on the target (D-018).
    """
    from deploys.steps import ensure_ship, image_tag
    from providers.fakes import FakeImageRegistry

    transport = ShipTransport()
    registry = FakeImageRegistry()
    target = SimpleNamespace(pk=7)
    desired = _desired(transport, registry=registry, target=target)
    tag = image_tag(GIT_SHA, desired["manifest_body"])

    first = ensure_ship(desired)
    assert first["status"] == "shipped"
    transport.calls.clear()
    registry.calls.clear()
    second = ensure_ship(desired)

    assert second["status"] == "skipped"
    assert transport.mutating_calls() == []
    assert registry.mutating_calls() == []
    assert transport.calls == [("probe", ["docker", "image", "inspect", tag])]
