"""ZT-02: API local_path is production-off and confined to an operator root.

What would make these fail: accepting local_path with sources disabled, resolving
outside HUB_LOCAL_SOURCE_ROOT, or archiving vault.key/.env/VCS/special files.
"""
import os
import tarfile
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from django.test import override_settings

from core.local_sources import (
    LocalSourceError,
    iter_archive_members,
    refuse_api_local_path,
    resolve_local_source,
)
from deploys.steps import _context_tar

pytestmark = pytest.mark.django_db

REPO = Path(__file__).resolve().parent.parent


def _tree(tmp_path):
    root = tmp_path / "sources"
    project = root / "app"
    project.mkdir(parents=True)
    (project / "main.py").write_text("print('ok')\n")
    return root, project


@override_settings(HUB_ALLOW_LOCAL_SOURCES=False, HUB_LOCAL_SOURCE_ROOT="")
def test_api_local_path_refused_when_sources_disabled(tmp_path):
    _root, project = _tree(tmp_path)
    with pytest.raises(LocalSourceError, match="disabled"):
        refuse_api_local_path(str(project))


@override_settings(HUB_ALLOW_LOCAL_SOURCES=True, HUB_LOCAL_SOURCE_ROOT="")
def test_api_local_path_without_root_is_refused(tmp_path):
    with pytest.raises(LocalSourceError, match="HUB_LOCAL_SOURCE_ROOT"):
        refuse_api_local_path("/etc")
    with pytest.raises(LocalSourceError):
        resolve_local_source("/", require_root=False)


@override_settings(HUB_ALLOW_LOCAL_SOURCES=True, HUB_LOCAL_SOURCE_ROOT="")
def test_archive_and_adopt_require_the_source_root(tmp_path):
    """ZT-22: a stored local_path must not archive host-wide when the root is unset."""
    project = tmp_path / "app"
    project.mkdir()
    (project / "main.py").write_text("print(1)\n")
    with pytest.raises(LocalSourceError, match="HUB_LOCAL_SOURCE_ROOT"):
        list(iter_archive_members(str(project)))
    from provision.adopt import _project_tree

    class Fake:
        local_path = str(project)

    assert _project_tree(Fake()) is None


@override_settings(HUB_ALLOW_LOCAL_SOURCES=True)
def test_confinement_rejects_root_etc_escapes_and_the_source_root(tmp_path, settings):
    root, project = _tree(tmp_path)
    settings.HUB_LOCAL_SOURCE_ROOT = str(root)
    assert resolve_local_source(str(project)) == project.resolve()
    for denied in ("/", "/etc", "/etc/deploy-hub", str(root)):
        with pytest.raises(LocalSourceError):
            resolve_local_source(denied)
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(LocalSourceError, match="outside"):
        resolve_local_source(str(outside))
    escaped = project / ".." / ".." / "outside"
    escaped.mkdir(exist_ok=True)
    with pytest.raises(LocalSourceError):
        resolve_local_source(str(escaped))


@override_settings(HUB_ALLOW_LOCAL_SOURCES=True)
def test_symlink_escape_and_validation_use_swap_are_rejected(tmp_path, settings):
    root, project = _tree(tmp_path)
    settings.HUB_LOCAL_SOURCE_ROOT = str(root)
    link = root / "escape"
    link.symlink_to("/etc")
    with pytest.raises(LocalSourceError):
        resolve_local_source(str(link))

    resolved = resolve_local_source(str(project))
    assert resolved == project.resolve()
    swapped = root / "swapped-away"
    project.rename(swapped)
    project.symlink_to("/etc")
    with pytest.raises(LocalSourceError):
        list(iter_archive_members(str(project)))
    with pytest.raises(RuntimeError):
        _context_tar(str(project), "FROM scratch\n")


@override_settings(HUB_ALLOW_LOCAL_SOURCES=True)
def test_special_files_and_oversized_contexts_are_rejected(tmp_path, settings):
    root, project = _tree(tmp_path)
    settings.HUB_LOCAL_SOURCE_ROOT = str(root)
    fifo = project / "queue"
    os.mkfifo(fifo)
    members = dict(iter_archive_members(str(project)))
    assert "queue" not in members
    assert "main.py" in members

    huge = project / "blob.bin"
    huge.write_bytes(b"x" * (32 * 1024 * 1024 + 1))
    with pytest.raises(LocalSourceError, match="size"):
        list(iter_archive_members(str(project)))


@override_settings(HUB_ALLOW_LOCAL_SOURCES=True)
def test_allowed_tree_scans_and_builds_without_secrets(tmp_path, settings):
    from scanner.core import scan

    root, project = _tree(tmp_path)
    settings.HUB_LOCAL_SOURCE_ROOT = str(root)
    (project / "vault.key").write_text("kek")
    (project / ".env").write_text("SECRET=1")
    (project / ".env.local").write_text("SECRET=2")
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("secret")
    (project / "ok.txt").write_text("hello")
    sock = project / "app.sock"
    try:
        import socket

        s = socket.socket(socket.AF_UNIX)
        s.bind(str(sock))
        s.close()
    except OSError:
        sock = None

    report = scan(str(resolve_local_source(str(project))))
    assert isinstance(report, dict)
    archive = _context_tar(str(project), "FROM scratch\n")
    with tarfile.open(fileobj=BytesIO(archive), mode="r") as tf:
        names = set(tf.getnames())
    assert "ok.txt" in names
    assert "main.py" in names
    assert "Dockerfile" in names
    assert "vault.key" not in names
    assert ".env" not in names
    assert ".env.local" not in names
    assert ".git/config" not in names
    if sock is not None:
        assert "app.sock" not in names


@override_settings(HUB_ALLOW_LOCAL_SOURCES=False)
def test_project_create_api_refuses_local_path_in_production_default(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user("src-op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    r = client.post(
        "/api/v1/projects/",
        data={
            "name": "local-off",
            "local_path": "/tmp/anything",
            "domain": "local-off.example.test",
        },
        content_type="application/json",
    )
    assert r.status_code == 400, r.content
    assert "local_path" in r.json()["errors"]


def test_probe_workers_do_not_mount_the_kek():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    probes = compose["services"]["worker-probes"]
    mounts = {item.split(":")[0] for item in probes.get("volumes") or []}
    assert "hub-vault" not in mounts
    beat = compose["services"]["beat"]
    beat_mounts = {item.split(":")[0] for item in beat.get("volumes") or []}
    assert "hub-vault" not in beat_mounts
