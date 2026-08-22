"""ensure_start: recreate stops the old writer first; blue-green starts alongside (N1 / D6)."""
import pytest

from core.transport import CommandResult, FakeTransport

IMAGE_TAG = "abc123-deadbeefdeadbeef"


class StartTransport(FakeTransport):
    """Inspect keyed on full argv. A container exists only after this process ran it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.containers = {}

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv and argv[0] == "docker" and "inspect" in argv:
            if "volume" in argv or "image" in argv:
                canned = self.responses.get(argv[0])
                if canned is None:
                    return CommandResult(argv)
                return CommandResult(argv, **canned)
            name = _inspect_target(argv)
            state = self.containers.get(name)
            if state is None:
                return CommandResult(argv, exit_code=1, stderr="Error: No such container")
            stdout = "true" if state == "running" else "false"
            return CommandResult(argv, exit_code=0, stdout=stdout)
        if argv[:2] == ["docker", "ps"]:
            running = [n for n, s in self.containers.items() if s == "running"]
            return CommandResult(argv, exit_code=0, stdout="\n".join(running))
        canned = self.responses.get(argv[0])
        if canned is None:
            return CommandResult(argv)
        return CommandResult(argv, **canned)

    def run(self, argv, *, timeout=60):
        result = super().run(argv, timeout=timeout)
        argv = list(argv)
        if argv[:2] == ["docker", "run"]:
            name = _flag_value(argv, "--name")
            if name:
                self.containers[name] = "running"
        if argv[:2] == ["docker", "start"] and len(argv) >= 3:
            self.containers[argv[2]] = "running"
        if argv[:2] == ["docker", "stop"] and len(argv) >= 3:
            name = argv[2]
            if name in self.containers:
                self.containers[name] = "exited"
        if argv[:2] == ["docker", "rm"]:
            name = argv[-1]
            self.containers.pop(name, None)
        return result


def _inspect_target(argv):
    for part in reversed(argv):
        if part.startswith("-") or part.startswith("{{") or part in {"docker", "inspect"}:
            continue
        return part
    return argv[-1]


def _flag_value(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _run_argvs(transport):
    return [argv for kind, argv in transport.calls if kind == "run"]


def _mutating_runs(transport):
    return [argv for kind, argv in transport.mutating_calls() if kind == "run"]


def _stop_indexes(runs, name):
    return [
        i for i, argv in enumerate(runs)
        if argv[:2] == ["docker", "stop"] and name in argv
    ]


def _run_indexes(runs, name):
    return [
        i for i, argv in enumerate(runs)
        if argv[:2] == ["docker", "run"] and name in argv
    ]


def _inspects(transport):
    return [
        (kind, argv) for kind, argv in transport.calls
        if kind in ("probe", "run")
        and isinstance(argv, list)
        and argv
        and argv[0] == "docker"
        and ("inspect" in argv or argv[:2] == ["docker", "ps"])
        and "volume" not in argv
        and "image" not in argv
    ]


def _site(*, slug, deploy_strategy="blue_green"):
    from core.models import Project, Site

    project = Project.objects.create(name=slug, slug=f"p-start-{slug}")
    from dns_fixtures import default_dns_zone

    return Site.objects.create(
        project=project,
        name=slug,
        dns_zone=default_dns_zone(),
        deploy_strategy=deploy_strategy,
    )


def _desired(transport, *, slug="app", deployment_id=7, body=None, site=None,
             old_container=None):
    desired = {
        "transport": transport,
        "site_slug": slug,
        "deployment_id": deployment_id,
        "manifest_body": body if body is not None else {},
        "image_tag": IMAGE_TAG,
    }
    if site is not None:
        desired["site"] = site
    if old_container is not None:
        desired["old_container"] = old_container
    return desired


@pytest.mark.req("PIPE-N1-DEPLOY-STRATEGY")
@pytest.mark.django_db
def test_recreate_stops_old_before_new_opens_db():
    """Recreate must docker stop the old writer before docker run of the new name.

    What would make this fail: starting the new container first (two writers on
    the volume/DB), omitting docker stop, or docker rm of the old container.
    """
    from deploys.steps import ensure_start

    slug = "takko"
    deployment_id = 11
    green = f"site-{slug}-{deployment_id}"
    old = "site-takko-10"
    site = _site(slug=slug, deploy_strategy="recreate")
    transport = StartTransport()
    transport.containers[old] = "running"

    ensure_start(_desired(
        transport,
        slug=slug,
        deployment_id=deployment_id,
        body={"deploy_strategy": "recreate"},
        site=site,
        old_container=old,
    ))

    runs = _mutating_runs(transport)
    stop_at = _stop_indexes(runs, old)
    run_at = _run_indexes(runs, green)
    assert stop_at, f"expected docker stop {old} in mutating_calls, got {runs}"
    assert run_at, f"expected docker run of {green} in mutating_calls, got {runs}"
    assert stop_at[0] < run_at[0]
    assert not any(argv[:2] == ["docker", "rm"] and old in argv for argv in runs)
    site.refresh_from_db()
    assert site.maintenance_until is not None
    inspects = _inspects(transport)
    assert inspects
    assert all(kind == "probe" for kind, argv in inspects)
    assert not any(
        kind == "run" and ("inspect" in argv or argv[:2] == ["docker", "ps"])
        for kind, argv in transport.calls
        if isinstance(argv, list)
    )


@pytest.mark.req("PIPE-N1-DEPLOY-STRATEGY")
def test_blue_green_starts_alongside():
    """Blue-green docker run of green must not be preceded by docker stop of old.

    What would make this fail: stopping the old writer before the new container
    starts, or skipping docker run of the deterministic green name.
    """
    from deploys.steps import ensure_start

    slug = "blog"
    deployment_id = 22
    green = f"site-{slug}-{deployment_id}"
    old = "site-blog-21"
    transport = StartTransport()
    transport.containers[old] = "running"

    ensure_start(_desired(
        transport,
        slug=slug,
        deployment_id=deployment_id,
        body={"deploy_strategy": "blue_green"},
        old_container=old,
    ))

    runs = _mutating_runs(transport)
    run_at = _run_indexes(runs, green)
    assert run_at, f"expected docker run of {green}, got {runs}"
    stop_at = _stop_indexes(runs, old)
    assert not any(i < run_at[0] for i in stop_at)
    inspects = _inspects(transport)
    assert inspects
    assert all(kind == "probe" for kind, argv in inspects)


@pytest.mark.req("PIPE-N1-DEPLOY-STRATEGY")
@pytest.mark.django_db
def test_local_state_site_cannot_override_off_recreate():
    """local_state / exclusive_upstream force recreate even when the site is blue_green.

    What would make this fail: honouring Site.deploy_strategy=blue_green and
    starting alongside, leaving two writers on exclusive local state.
    """
    from core.models import Site
    from deploys.steps import ensure_start

    slug = "feeds"
    deployment_id = 3
    green = f"site-{slug}-{deployment_id}"
    old = "site-feeds-2"
    site = _site(slug=slug, deploy_strategy=Site.DeployStrategy.BLUE_GREEN)
    assert site.deploy_strategy == Site.DeployStrategy.BLUE_GREEN
    transport = StartTransport()
    transport.containers[old] = "running"

    ensure_start(_desired(
        transport,
        slug=slug,
        deployment_id=deployment_id,
        body={"local_state": True, "deploy_strategy": "blue_green"},
        site=site,
        old_container=old,
    ))

    runs = _mutating_runs(transport)
    stop_at = _stop_indexes(runs, old)
    run_at = _run_indexes(runs, green)
    assert stop_at, f"expected docker stop {old} despite site blue_green, got {runs}"
    assert run_at, f"expected docker run of {green}, got {runs}"
    assert stop_at[0] < run_at[0]

    transport.calls.clear()
    transport.containers.clear()
    transport.containers[old] = "running"
    site.deploy_strategy = Site.DeployStrategy.BLUE_GREEN
    site.save(update_fields=["deploy_strategy"])
    ensure_start(_desired(
        transport,
        slug=slug,
        deployment_id=deployment_id + 1,
        body={"exclusive_upstream": True},
        site=site,
        old_container=old,
    ))
    exclusive_runs = _mutating_runs(transport)
    exclusive_green = f"site-{slug}-{deployment_id + 1}"
    stop_ex = _stop_indexes(exclusive_runs, old)
    run_ex = _run_indexes(exclusive_runs, exclusive_green)
    assert stop_ex and run_ex and stop_ex[0] < run_ex[0]


@pytest.mark.req("PIPE-N1-DEPLOY-STRATEGY")
@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_second_start_zero_mutating_calls():
    """A running green container is adopted; the second start mutates nothing.

    What would make this fail: inspect via run, a second docker run of the same
    name, or any put after the named container is already running.
    """
    from deploys.steps import ensure_start

    slug = "wiki"
    deployment_id = 9
    green = f"site-{slug}-{deployment_id}"
    transport = StartTransport()
    desired = _desired(
        transport,
        slug=slug,
        deployment_id=deployment_id,
        body={"deploy_strategy": "blue_green"},
    )
    ensure_start(desired)
    assert green in transport.containers
    assert transport.containers[green] == "running"
    assert _run_indexes(_mutating_runs(transport), green)

    transport.calls.clear()
    ensure_start(desired)
    assert transport.mutating_calls() == []
    inspects = _inspects(transport)
    assert inspects
    assert all(kind == "probe" for kind, argv in inspects)
    assert not any(
        kind == "run" and ("inspect" in argv or argv[:2] == ["docker", "ps"])
        for kind, argv in transport.calls
        if isinstance(argv, list)
    )


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_docker_run_argv_includes_restart_unless_stopped():
    """docker run must pass --restart unless-stopped as two tokens before the image.

    What would make this fail: omitting the policy, placing it after the image
    tag (so Docker treats it as the command), or using one --restart=unless-stopped
    token.
    """
    from deploys.steps import _docker_run_argv, ensure_start

    transport = StartTransport()
    ensure_start(_desired(transport, slug="relp2", deployment_id=8))
    runs = [argv for argv in _run_argvs(transport) if argv[:2] == ["docker", "run"]]
    assert runs, transport.calls
    argv = runs[0]
    assert argv[-1] == IMAGE_TAG
    assert argv[-3:-1] == ["--restart", "unless-stopped"], argv

    built = _docker_run_argv({
        "image_tag": IMAGE_TAG,
        "site_slug": "relp2",
        "deployment_id": 8,
        "manifest_body": {},
    }, "site-relp2-8")
    assert built[-1] == IMAGE_TAG
    assert built[-3:-1] == ["--restart", "unless-stopped"], built


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_restart_flag_is_literal_argv_not_shell():
    """--restart and unless-stopped are two argv tokens, never a shell string.

    What would make this fail: returning a joined string, interpolating
    f"--restart {policy}", or stuffing both words into one token.
    """
    from deploys.steps import _docker_run_argv

    argv = _docker_run_argv({
        "image_tag": IMAGE_TAG,
        "site_slug": "relp2lit",
        "deployment_id": 1,
        "manifest_body": {},
    }, "site-relp2lit-1")
    assert isinstance(argv, list)
    assert all(isinstance(part, str) for part in argv)
    assert "--restart" in argv
    restart_at = argv.index("--restart")
    assert argv[restart_at + 1] == "unless-stopped"
    assert "--restart unless-stopped" not in argv
    assert "--restart=unless-stopped" not in argv
    assert not any(" " in part for part in argv)
