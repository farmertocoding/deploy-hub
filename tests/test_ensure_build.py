"""ensure_build: docker build on the target, vault-free context (SEC-B1 / D6)."""
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from core.transport import CommandResult, FakeTransport

GIT_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
VAULT_MARKER = b"VAULT-TEST-PLAINTEXT-MARKER-do-not-log"


class StepTransport(FakeTransport):
    """Inspect keyed on full argv. A tag exists only after this process built it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.images = set()

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv[:3] == ["docker", "image", "inspect"] and len(argv) >= 4:
            tag = argv[3]
            if tag in self.images:
                return CommandResult(argv, exit_code=0, stdout=tag)
            self._last_inspect_miss = tag
            return CommandResult(argv, exit_code=1, stderr="Error: No such image")
        canned = self.responses.get(argv[0])
        if canned is None:
            return CommandResult(argv)
        return CommandResult(argv, **canned)

    def run(self, argv, *, timeout=60):
        result = super().run(argv, timeout=timeout)
        argv = list(argv)
        if argv and argv[0] == "docker" and "build" in argv and "-t" in argv:
            self.images.add(argv[argv.index("-t") + 1])
        if argv[:2] == ["docker", "load"]:
            pending = getattr(self, "_last_inspect_miss", None)
            if pending:
                self.images.add(pending)
        return result


def _source_tree(tmp_path):
    (tmp_path / "app.js").write_text("console.log('ok');\n")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n')
    return tmp_path


def _desired(source_dir, transport, *, body=None, git_sha=GIT_SHA):
    return {
        "transport": transport,
        "source_dir": str(source_dir),
        "git_sha": git_sha,
        "manifest_body": body if body is not None else {"runtime": "node"},
    }


def _put_bytes(transport):
    puts = [remote for kind, remote in transport.calls if kind == "put"]
    assert puts, "expected a put of the build context"
    payload = transport.files[puts[0]]
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    return Path(payload).read_bytes()


def _tar_member_name(name):
    return name[2:] if name.startswith("./") else name


def _tar_names(payload):
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r") as tf:
        return [_tar_member_name(m.name) for m in tf.getmembers() if m.isfile()]


def _tar_text(payload, name):
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r") as tf:
        member = tf.extractfile(name) or tf.extractfile("./" + name)
        assert member is not None, f"{name} missing from context tar"
        return member.read().decode()


def _build_argv(transport):
    runs = [
        argv for kind, argv in transport.calls
        if kind == "run" and argv and argv[0] == "docker" and "build" in argv
    ]
    assert runs, "expected docker build on transport.run"
    return runs[0]


@pytest.mark.req("SEC-B1-BUILD-OFFHUB")
def test_docker_build_argv_runs_on_target_not_hub(tmp_path, monkeypatch):
    """docker build argv is transport.run on the target, never Hub subprocess.

    What would make this fail: subprocess/Popen docker on the Hub, or no
    docker build on the Transport.
    """
    from deploys.steps import ensure_build, image_tag

    def forbid_hub_docker(cmd, *args, **kwargs):
        tokens = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        joined = " ".join(str(t) for t in tokens)
        if "docker" in joined:
            raise AssertionError(f"Hub must not invoke local docker: {cmd!r}")
        raise AssertionError(f"unexpected Hub subprocess: {cmd!r}")

    monkeypatch.setattr(subprocess, "run", forbid_hub_docker)
    monkeypatch.setattr(subprocess, "Popen", forbid_hub_docker)
    monkeypatch.setattr(subprocess, "call", forbid_hub_docker)
    monkeypatch.setattr(subprocess, "check_call", forbid_hub_docker)
    monkeypatch.setattr(subprocess, "check_output", forbid_hub_docker)

    transport = StepTransport()
    body = {"runtime": "node"}
    desired = _desired(_source_tree(tmp_path), transport, body=body)
    ensure_build(desired)

    argv = _build_argv(transport)
    tag = image_tag(GIT_SHA, body)
    assert "-t" in argv
    assert argv[argv.index("-t") + 1] == tag
    inspects = [
        (kind, a) for kind, a in transport.calls
        if kind in ("probe", "run") and a[:3] == ["docker", "image", "inspect"]
    ]
    assert inspects
    assert all(kind == "probe" for kind, a in inspects)


@pytest.mark.req("SEC-B1-BUILD-OFFHUB")
def test_build_context_contains_no_env_file_or_vault_material(tmp_path):
    """Env files and planted vault markers never enter the shipped context.

    What would make this fail: putting .env, .env.*, *.env, following a
    file symlink to vault/env bytes, or shipping a planted vault marker.
    """
    from deploys.steps import ensure_build

    root = _source_tree(tmp_path)
    (root / ".env").write_text("SECRET=should-not-ship\n")
    (root / "prod.env").write_text("TOKEN=nope\n")
    (root / ".env.local").write_text("LOCAL=must-not-ship\n")
    (root / ".env.production").write_text("PROD=must-not-ship\n")
    (root / "nested").mkdir()
    (root / "nested" / ".env").write_text("NESTED=no\n")
    (root / "leaked.bin").write_bytes(VAULT_MARKER)
    (root / "looks-safe.js").symlink_to(root / ".env")
    (root / "also-safe.txt").symlink_to(root / "leaked.bin")

    transport = StepTransport()
    ensure_build(_desired(root, transport))

    payload = _put_bytes(transport)
    names = _tar_names(payload)
    assert "app.js" in names
    assert ".env" not in names
    assert "prod.env" not in names
    assert ".env.local" not in names
    assert ".env.production" not in names
    assert "nested/.env" not in names
    assert "leaked.bin" not in names
    assert "looks-safe.js" not in names
    assert "also-safe.txt" not in names
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            data = tf.extractfile(member).read()
            assert data != VAULT_MARKER
            assert b"SECRET=should-not-ship" not in data
            assert b"LOCAL=must-not-ship" not in data
            assert b"PROD=must-not-ship" not in data


@pytest.mark.req("SEC-B1-BUILD-OFFHUB")
@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_second_build_zero_mutating_calls(tmp_path):
    """Same git sha + manifest hash reuses the tag; second ensure_build is a skip.

    What would make this fail: a new tag, inspect via run, or any run/put on
    the second call.
    """
    from deploys.steps import ensure_build, image_tag

    transport = StepTransport()
    body = {"runtime": "node"}
    desired = _desired(_source_tree(tmp_path), transport, body=body)
    tag = image_tag(GIT_SHA, body)
    assert tag == image_tag(GIT_SHA, body)

    ensure_build(desired)
    assert tag in transport.images
    assert _build_argv(transport)

    transport.calls.clear()
    ensure_build(desired)
    assert transport.mutating_calls() == []
    assert transport.calls == [("probe", ["docker", "image", "inspect", tag])]


@pytest.mark.req("SEC-B1-BUILD-OFFHUB")
@pytest.mark.django_db
def test_generated_dockerfile_uses_npm_ci_or_hashed_pip(tmp_path):
    """Generated Dockerfiles pin installs from Manifest.body: npm ci or hashed pip.

    What would make this fail: npm install, pip without --require-hashes, or
    pulling a template from scanner instead of Manifest.body.
    """
    from core.models import Project, Site
    from deploys.models import Manifest
    from deploys.steps import ensure_build

    project = Project.objects.create(name="p", slug="p-df")
    site = Site.objects.create(project=project, name="df")
    node_manifest = Manifest.objects.create(
        site=site, version=1, body={"runtime": "node"},
    )
    py_manifest = Manifest.objects.create(
        site=site, version=2, body={"runtime": "python"},
    )

    root = _source_tree(tmp_path)
    node_transport = StepTransport()
    ensure_build(_desired(root, node_transport, body=node_manifest.body))
    node_df = _tar_text(_put_bytes(node_transport), "Dockerfile")
    assert "npm ci" in node_df
    assert "npm install" not in node_df

    py_transport = StepTransport()
    ensure_build(_desired(root, py_transport, body=py_manifest.body))
    py_df = _tar_text(_put_bytes(py_transport), "Dockerfile")
    assert "pip install --require-hashes" in py_df
    assert "npm install" not in py_df


@pytest.mark.req("REL-P4-ARTIFACT-SNAPSHOTS")
def test_overlay_dockerfile_is_packed_not_body_template(tmp_path):
    """desired['dockerfile'] is packed even when it differs from body generation.

    What would make this fail: ensure_build still tarring _dockerfile_from_body(body)
    while the overlay holds snapshot bytes.
    """
    from deploys.steps import _dockerfile_from_body, ensure_build

    body = {"runtime": "node"}
    generated = _dockerfile_from_body(body)
    overlay = "FROM alpine:3.20\n# rollback-snapshot-bytes\n"
    assert overlay != generated
    assert "npm ci" in generated

    transport = StepTransport()
    desired = _desired(_source_tree(tmp_path), transport, body=body)
    desired["dockerfile"] = overlay
    ensure_build(desired)

    packed = _tar_text(_put_bytes(transport), "Dockerfile")
    assert packed == overlay
    assert "npm ci" not in packed
