"""ensure_volume: per-Site docker volumes; create on miss; never rm (N5 / D6)."""
import pytest

from core.transport import CommandResult, FakeTransport


class VolumeTransport(FakeTransport):
    """Inspect/create keyed on full argv. A volume exists only after create."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.volumes = set()

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv[:3] == ["docker", "volume", "inspect"] and len(argv) >= 4:
            name = argv[3]
            if name in self.volumes:
                return CommandResult(argv, exit_code=0, stdout=name)
            return CommandResult(argv, exit_code=1, stderr="Error: No such volume")
        canned = self.responses.get(argv[0])
        if canned is None:
            return CommandResult(argv)
        return CommandResult(argv, **canned)

    def run(self, argv, *, timeout=60):
        result = super().run(argv, timeout=timeout)
        argv = list(argv)
        if argv[:3] == ["docker", "volume", "create"] and len(argv) >= 4:
            self.volumes.add(argv[3])
        return result


def _volume_rm_argvs(transport):
    found = []
    for kind, payload in transport.mutating_calls():
        if kind != "run" or not isinstance(payload, list):
            continue
        argv = list(payload)
        if argv[-2:] == ["volume", "rm"]:
            found.append(argv)
            continue
        try:
            i = argv.index("volume")
        except ValueError:
            continue
        if i + 1 < len(argv) and argv[i + 1] == "rm":
            found.append(argv)
    return found


def _creates(transport):
    return [
        argv for kind, argv in transport.calls
        if kind == "run" and argv[:3] == ["docker", "volume", "create"]
    ]


def _inspects(transport):
    return [
        (kind, argv) for kind, argv in transport.calls
        if kind in ("probe", "run") and argv[:3] == ["docker", "volume", "inspect"]
    ]


def _site_pair(slug):
    from core.models import Project, Site
    from deploys.models import Deployment, Manifest

    project = Project.objects.create(name=slug, slug=f"p-vol-{slug}")
    from dns_fixtures import default_dns_zone

    site = Site.objects.create(project=project, name=slug,
                               dns_zone=default_dns_zone())
    manifest = Manifest.objects.create(
        site=site,
        version=1,
        body={"volumes": []},
    )
    d1 = Deployment.objects.create(manifest=manifest)
    d2 = Deployment.objects.create(manifest=manifest)
    return site, manifest, d1, d2


@pytest.mark.req("PIPE-N5-VOLUMES-MODELED")
@pytest.mark.django_db
def test_volume_is_per_site_not_per_deployment():
    """Docker volume names are site-{slug}-data, never a deployment id.

    What would make this fail: baking a Deployment pk into the volume name,
    two sites sharing one docker name, or skipping SiteVolume upsert.
    """
    from core.models import SiteVolume
    from deploys.steps import ensure_volume

    site_a, man_a, a1, a2 = _site_pair("alpha")
    site_b, man_b, b1, b2 = _site_pair("beta")
    transport = VolumeTransport()

    for _dep in (a1, a2):
        ensure_volume({
            "transport": transport,
            "site_slug": "alpha",
            "manifest_body": man_a.body,
            "site": site_a,
        })
    for _dep in (b1, b2):
        ensure_volume({
            "transport": transport,
            "site_slug": "beta",
            "manifest_body": man_b.body,
            "site": site_b,
        })

    created_names = [argv[3] for argv in _creates(transport)]
    assert created_names.count("site-alpha-data") == 1
    assert created_names.count("site-beta-data") == 1
    for dep in (a1, a2, b1, b2):
        assert all(str(dep.pk) not in name for name in created_names)

    inspects = _inspects(transport)
    assert inspects
    assert all(kind == "probe" for kind, argv in inspects)
    inspect_names = [argv[3] for kind, argv in inspects]
    assert "site-alpha-data" in inspect_names
    assert "site-beta-data" in inspect_names
    for dep in (a1, a2, b1, b2):
        assert all(str(dep.pk) not in name for name in inspect_names)

    assert SiteVolume.objects.filter(site=site_a, name="site-alpha-data").exists()
    assert SiteVolume.objects.filter(site=site_b, name="site-beta-data").exists()
    assert SiteVolume.objects.filter(site=site_a).count() == 1
    assert SiteVolume.objects.filter(site=site_b).count() == 1


@pytest.mark.req("PIPE-N5-VOLUMES-MODELED")
@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_second_ensure_volume_zero_mutating_calls():
    """Present volumes are probed then skipped; second call mutates nothing.

    What would make this fail: inspect via run, a second docker volume create,
    or any put on the replay.
    """
    from deploys.steps import ensure_volume

    transport = VolumeTransport()
    body = {
        "volumes": [
            {
                "name": "site-gamma-data",
                "container_path": "/data",
                "backup_policy": "directory_sync",
            },
            {
                "name": "site-gamma-cache",
                "container_path": "/cache",
                "backup_policy": "none",
            },
        ],
    }
    desired = {
        "transport": transport,
        "site_slug": "gamma",
        "manifest_body": body,
    }
    ensure_volume(desired)
    created = [argv[3] for argv in _creates(transport)]
    assert "site-gamma-data" in created
    assert "site-gamma-cache" in created
    assert created.count("site-gamma-data") == 1
    inspects = _inspects(transport)
    assert inspects
    assert all(kind == "probe" for kind, argv in inspects)

    transport.calls.clear()
    ensure_volume(desired)
    assert transport.mutating_calls() == []
    assert all(kind == "probe" for kind, argv in _inspects(transport))


@pytest.mark.req("PIPE-N5-VOLUMES-MODELED")
def test_rollback_path_does_not_call_volume_rm():
    """Rollback explicitly refuses docker volume rm; volumes survive.

    What would make this fail: issuing docker volume rm on the rollback path,
    or a silent no-op that never records the T1 refusal.
    """
    from deploys.steps import ensure_volume, ensure_volume_rollback

    transport = VolumeTransport()
    desired = {
        "transport": transport,
        "site_slug": "delta",
        "manifest_body": {"volumes": []},
    }
    ensure_volume(desired)
    assert "site-delta-data" in transport.volumes
    transport.calls.clear()

    result = ensure_volume_rollback(desired)
    assert result["status"] == "refused"
    assert _volume_rm_argvs(transport) == []
    assert not any(
        isinstance(payload, list) and payload[-2:] == ["volume", "rm"]
        for kind, payload in transport.mutating_calls()
    )
    assert "site-delta-data" in transport.volumes
