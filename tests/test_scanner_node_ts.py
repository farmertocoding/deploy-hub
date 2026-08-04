"""node-ts scanner module: §S3 detection, §S4 static checks, and the Q7 fixture
contract — positive pass over sample-node-site plus the MUTATIONS.md negative
matrix (one edit per mutation; exactly the named check flips tier)."""
import json
import pathlib
import shutil

import pytest

from scanner import core
from scanner.modules import node_ts

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = REPO / "sample-node-site"
DJANGO_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "django"

SERVER_PKG = pathlib.Path("packages/server/package.json")
SERVER_TSCONFIG = pathlib.Path("packages/server/tsconfig.json")
SERVER_INDEX = pathlib.Path("packages/server/src/index.ts")
SERVER_INGEST = pathlib.Path("packages/server/src/ingest.ts")

# The designed pristine-tree tier of every node-ts static check (MUTATIONS.md
# positive-fire inventory): warnings/advice here fire POSITIVELY by design —
# local-state and exclusive-upstream are honest findings, never blockers.
EXPECTED_TIERS = {
    "node-ts.monorepo": "ok",
    "node-ts.service-package": "ok",
    "node-ts.recognized-deps": "ok",
    "node-ts.worker-threads": "ok",
    "node-ts.offline-component": "ok",
    "node-ts.strict-build": "ok",
    "node-ts.compiled-js": "ok",
    "node-ts.engines-pin": "ok",
    "node-ts.bun-dev-only": "ok",
    "node-ts.fastify-serving": "ok",
    "node-ts.graceful-shutdown": "ok",
    "node-ts.ws-heartbeat": "ok",
    "node-ts.readiness-pattern": "ok",
    "node-ts.ingest-reconnect": "ok",
    "node-ts.ingest-staleness": "ok",
    "node-ts.ingest-backfill": "ok",
    "node-ts.exclusive-upstream": "warning",
    "node-ts.local-state": "warning",
    "node-ts.secrets-env": "advice",
    "node-ts.jobs-image": "advice",
}


@pytest.fixture(scope="module")
def pristine_report():
    return core.scan(FIXTURE)


def tier_map(report):
    return {c["id"]: c["tier"] for c in report["checks"]}


def by_id(report, check_id):
    matches = [c for c in report["checks"] if c["id"] == check_id]
    assert len(matches) == 1, f"{check_id} appeared {len(matches)} times"
    return matches[0]


def copy_fixture(tmp_path):
    site = tmp_path / "site"
    shutil.copytree(FIXTURE, site)
    return site


def edit_json(path, mutate):
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text, f"expected substring missing from {path.name}: {old[:60]!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ── §S3 detection (SCAN-S3-DETECTION-RULES) ─────────────────────────────────────

@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_detection_rules_all_fire_on_the_fixture(pristine_report):
    assert node_ts.module.detect(FIXTURE) is True
    assert pristine_report["modules"] == ["node-ts"]
    mono = by_id(pristine_report, "node-ts.monorepo")
    assert mono["tier"] == "ok"
    assert "server" in mono["detail"] and "web" in mono["detail"]
    svc = by_id(pristine_report, "node-ts.service-package")
    assert svc["tier"] == "ok" and "server" in svc["title"]
    deps = by_id(pristine_report, "node-ts.recognized-deps")
    for name in ("fastify", "ws", "zod", "ccxt"):
        assert name in deps["detail"]
    assert "armed" in deps["detail"]  # ccxt arms the ingestion checks
    workers = by_id(pristine_report, "node-ts.worker-threads")
    assert workers["tier"] == "ok" and "detected" in workers["title"]
    offline = by_id(pristine_report, "node-ts.offline-component")
    assert offline["tier"] == "ok"
    for name in ("vectorbt", "polars", "duckdb"):
        assert name in offline["detail"]
    # engines.node + tsconfig strict are recorded through their checks
    assert by_id(pristine_report, "node-ts.engines-pin")["tier"] == "ok"
    assert by_id(pristine_report, "node-ts.strict-build")["tier"] == "ok"
    # data-path heuristics fire the local-state finding
    state = by_id(pristine_report, "node-ts.local-state")
    assert state["tier"] == "warning"
    for token in (".parquet", "app.sqlite3", "levels.duckdb"):
        assert token in state["detail"]


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_detect_rejects_bare_and_django_trees(tmp_path):
    assert node_ts.module.detect(tmp_path) is False  # no manifests at all
    for name in ("uv_asgi", "legacy_bad", "pip_wsgi"):
        assert node_ts.module.detect(DJANGO_FIXTURES / name) is False, name


def test_registered_once_as_a_framework_module():
    import scanner.modules  # noqa: F401 — importing registers all modules

    framework, fallback = core.registered_modules()
    assert [m.name for m in framework].count("node-ts") == 1
    assert "node-ts" not in [m.name for m in fallback]


# ── Q7 positive pass: every check fires at its designed tier ────────────────────

@pytest.mark.req("Q7-NODE-FIXTURE")
def test_every_node_ts_check_fires_at_its_designed_tier(pristine_report):
    tiers = tier_map(pristine_report)
    static_tiers = {i: t for i, t in tiers.items()
                    if i.startswith("node-ts.") and t != "pending_sandbox"}
    assert static_tiers == EXPECTED_TIERS
    assert "blocker" not in tiers.values()
    # executing checks are EMITTED as sandbox specs, never run (§M1)
    jobs = {j["id"]: j["command"] for j in pristine_report["sandbox_jobs"]}
    assert jobs == {
        "node-ts.install": ["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"],
        "node-ts.tsc": ["pnpm", "exec", "tsc", "--noEmit"],
        "node-ts.build": ["pnpm", "run", "build"],
    }
    for job_id in jobs:
        assert tiers[job_id] == "pending_sandbox"
    # the offline pyproject (manual-v1) does not mask the committed pnpm lock
    assert tiers["core.lockfile"] == "ok"


@pytest.mark.req("Q7-NODE-FIXTURE")
def test_manifest_draft_has_recreate_volumes_healthz_and_jobs_image(pristine_report):
    draft = pristine_report["manifest_draft"]
    assert draft["deploy_strategy"] == "recreate"  # §N1: local state + §N4 exclusive
    assert draft["components"]["service"] == {
        "kind": "node-ts", "package": "server",
        "command": ["node", "dist/index.js"], "port": 8080,
    }
    (volume,) = draft["volumes"]
    assert volume["name"] == "site-data-data"
    assert volume["path"] == "data"
    kinds = {u["kind"] for u in volume["backup_policy"]["backup_units"]}
    assert kinds == {"sqlite_file", "directory_sync"}  # §N6 registry kinds
    assert volume["backup_policy"]["derived_excluded"] == ["data/levels.duckdb"]
    assert draft["jobs_image"] == {"from": "pyproject.toml", "status": "manual-v1"}
    healthz = draft["healthz"]
    assert healthz["liveness_path"] == "/healthz"
    assert healthz["readiness_path"] == "/healthz"
    assert healthz["data_staleness_threshold"] == 900  # ingestion detected
    # §N2 warm-up default (10–15 min → 600 s) on the module's own fragment; the
    # core deep-merge keeps its pre-set 120 default in the merged draft
    # (first-set-wins on scalars), so the module value is asserted here:
    fragment = node_ts.module.manifest_fragment(FIXTURE)
    assert fragment["healthz"]["warmup_timeout_s"] == 600


def test_secrets_env_advises_paper_keys_and_rides_core_secret_scan(pristine_report):
    res = by_id(pristine_report, "node-ts.secrets-env")
    assert res["tier"] == "advice"
    assert "ALPACA_SECRET" in res["detail"]
    assert "core.secret-scan" in res["detail"]
    assert "read-only" in res["fix_hint"] and "paper" in res["fix_hint"]


def test_exclusive_upstream_warns_and_explains_recreate(pristine_report):
    res = by_id(pristine_report, "node-ts.exclusive-upstream")
    assert res["tier"] == "warning"
    assert "alpaca" in res["detail"].lower()
    assert "recreate" in res["detail"]


def test_local_state_notes_duckdb_derived_and_sqlite_writers(pristine_report):
    res = by_id(pristine_report, "node-ts.local-state")
    assert "single-instance" in res["detail"]
    assert "excluded from backup" in res["detail"]  # DuckDB is derived (§N6)
    assert "WAL does not make concurrent" in res["detail"]


# ── readiness pattern (SCAN-S4-READINESS-PATTERN) ───────────────────────────────

@pytest.mark.req("SCAN-S4-READINESS-PATTERN")
def test_readiness_gate_pattern_detected_and_ungated_flagged(tmp_path, pristine_report):
    res = by_id(pristine_report, "node-ts.readiness-pattern")
    assert res["tier"] == "ok"
    assert "backfillDone" in res["detail"]  # the gating expression is reported
    assert "live" in res["detail"] and "checks" in res["detail"]  # pinned shape
    # drop the gating term -> pattern check flips (enforcement stays pipeline-side)
    site = copy_fixture(tmp_path)
    replace_once(site / SERVER_INDEX,
                 "ready: backfillDone && feed.connected,", "ready: true,")
    flipped = {c.id: c for c in node_ts.module.checks(site)}
    assert flipped["node-ts.readiness-pattern"].tier == "warning"
    assert "unconditionally" in flipped["node-ts.readiness-pattern"].title


@pytest.mark.req("SCAN-S4-READINESS-PATTERN")
def test_missing_healthz_is_a_warning_with_the_e9_fallback_note(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "svc", "main": "dist/index.js",
        "engines": {"node": "22"},
        "scripts": {"start": "node dist/index.js"},
        "dependencies": {"fastify": "^5.0.0"},
    }))
    src = tmp_path / "src"
    src.mkdir()
    (src / "index.ts").write_text(
        'const app = Fastify({ trustProxy: true, bodyLimit: 1024 });\n'
        'app.listen({ host: "0.0.0.0", port: Number(process.env.PORT ?? 3000) });\n')
    assert node_ts.module.detect(tmp_path) is True  # fastify dep alone detects
    checks = {c.id: c for c in node_ts.module.checks(tmp_path)}
    res = checks["node-ts.readiness-pattern"]
    assert res.tier == "warning"  # §E9/§V7: absence is a warning, never a blocker
    assert "E9" in res.detail and "TCP" in res.detail


# ── Q7 mutation matrix (MUTATIONS.md — one edit, exactly one check flips) ───────

def mutate_strict_false(site):  # MUTATIONS.md #1
    edit_json(site / SERVER_TSCONFIG,
              lambda d: d["compilerOptions"].__setitem__("strict", False))


def mutate_ts_node_start(site):  # MUTATIONS.md #8
    edit_json(site / SERVER_PKG,
              lambda d: d["scripts"].__setitem__("start", "ts-node src/index.ts"))


def mutate_remove_sigterm(site):  # MUTATIONS.md #2
    path = site / SERVER_INDEX
    text = path.read_text(encoding="utf-8")
    start = text.index('process.on("SIGTERM"')
    anchor = text.index("setTimeout(() => process.exit(1), 20_000).unref();")
    end = text.index("});", anchor) + len("});")
    path.write_text(text[:start] + text[end:], encoding="utf-8")


def mutate_remove_ready_gate(site):  # MUTATIONS.md #3
    replace_once(site / SERVER_INDEX,
                 "ready: backfillDone && feed.connected,", "ready: true,")


def mutate_remove_heartbeat(site):  # MUTATIONS.md #4
    path = site / SERVER_INDEX
    replace_once(path, 'ws.on("pong", () => {\n    ws.isAlive = true;\n  });\n', "")
    text = path.read_text(encoding="utf-8")
    i = text.index("const heartbeat = setInterval")
    j = text.index("}, HEARTBEAT_MS);") + len("}, HEARTBEAT_MS);")
    text = (text[:i] + text[j:]).replace("clearInterval(heartbeat);\n", "")
    path.write_text(text, encoding="utf-8")


def mutate_delete_lockfile(site):  # MUTATIONS.md #5
    (site / "pnpm-lock.yaml").unlink()


def mutate_committed_env_secret(site):  # MUTATIONS.md #6 — written at test time
    (site / ".env").write_text("ALPACA_SECRET=AKFAKEFAKEFAKEFAKE1234\n")


def mutate_remove_reconnect_backoff(site):  # MUTATIONS.md #7
    path = site / SERVER_INGEST
    text = path.read_text(encoding="utf-8")
    i = text.index("/**\n * Live stream")
    j = text.index("// --- small helpers")
    replacement = (
        "async function streamLoop(hooks: IngestHooks): Promise<void> {\n"
        "  const exchange = new ccxt.pro.binance({ enableRateLimit: true });\n"
        "  connected = true;\n"
        "  for (;;) {\n"
        '    const trades = await exchange.watchTrades("BTC/USDT");\n'
        "    lastTickMs = Date.now();\n"
        "    for (const t of trades) hooks.onBar(tradeToBar(t));\n"
        "  }\n"
        "}\n\n")
    text = text[:i] + replacement + text[j:]
    assert "backoff" not in text.lower()
    path.write_text(text, encoding="utf-8")


def mutate_remove_engines(site):  # MUTATIONS.md #9
    edit_json(site / SERVER_PKG, lambda d: d.pop("engines"))


MUTATIONS = [
    ("strict_false", mutate_strict_false, "node-ts.strict-build", "warning"),
    ("ts_node_start", mutate_ts_node_start, "node-ts.compiled-js", "warning"),
    ("remove_sigterm", mutate_remove_sigterm, "node-ts.graceful-shutdown", "warning"),
    ("remove_ready_gate", mutate_remove_ready_gate, "node-ts.readiness-pattern", "warning"),
    ("remove_heartbeat", mutate_remove_heartbeat, "node-ts.ws-heartbeat", "warning"),
    ("delete_lockfile", mutate_delete_lockfile, "core.lockfile", "warning"),
    ("committed_env_secret", mutate_committed_env_secret, "core.secret-scan", "blocker"),
    ("remove_reconnect_backoff", mutate_remove_reconnect_backoff,
     "node-ts.ingest-reconnect", "warning"),
    ("remove_engines", mutate_remove_engines, "node-ts.engines-pin", "warning"),
]


@pytest.mark.req("Q7-NODE-FIXTURE")
@pytest.mark.parametrize(("name", "mutate", "target", "expected"), MUTATIONS,
                         ids=[m[0] for m in MUTATIONS])
def test_mutation_flips_exactly_the_target_check(tmp_path, pristine_report,
                                                 name, mutate, target, expected):
    site = copy_fixture(tmp_path)
    mutate(site)
    report = core.scan(site)
    assert report["modules"] == ["node-ts"], name
    baseline, mutated = tier_map(pristine_report), tier_map(report)
    assert set(mutated) == set(baseline)  # no check appears or disappears
    assert baseline[target] != expected, f"{name}: pristine tree already failing"
    assert mutated[target] == expected
    changed = {i for i in baseline if mutated[i] != baseline[i]}
    assert changed == {target}, f"{name}: single-cause discipline violated: {changed}"


# ── further negatives beyond the documented matrix ──────────────────────────────

def test_bun_in_the_runtime_path_is_flagged(tmp_path, pristine_report):
    assert by_id(pristine_report, "node-ts.bun-dev-only")["tier"] == "ok"
    site = copy_fixture(tmp_path)  # bun as devDependency/test script is fine
    edit_json(site / SERVER_PKG,
              lambda d: d["scripts"].__setitem__("start", "bun src/index.ts"))
    checks = {c.id: c for c in node_ts.module.checks(site)}
    assert checks["node-ts.bun-dev-only"].tier == "warning"
    assert "bun" in checks["node-ts.bun-dev-only"].detail


def test_missing_trust_proxy_flags_fastify_serving(tmp_path):
    site = copy_fixture(tmp_path)
    replace_once(site / SERVER_INDEX, "trustProxy: true,", "")
    checks = {c.id: c for c in node_ts.module.checks(site)}
    res = checks["node-ts.fastify-serving"]
    assert res.tier == "warning"
    assert "trustProxy" in res.detail


# ── wizard (§S3 additions + §N4/§M4) ────────────────────────────────────────────

def test_wizard_questions_cover_package_data_workers_exposure_exclusive():
    questions = {q.id: q for q in node_ts.module.wizard_questions(FIXTURE)}
    assert set(questions) == {
        "node-ts.service-package", "node-ts.dev-packages", "node-ts.data-dir",
        "node-ts.worker-threads", "node-ts.exposure", "node-ts.exclusive-upstream",
    }
    pkg = questions["node-ts.service-package"]
    assert pkg.kind == "choice"
    assert pkg.default == "server"
    assert set(pkg.choices) == {"server", "web"}
    assert questions["node-ts.dev-packages"].default == "web"
    assert questions["node-ts.data-dir"].default == "data"
    workers = questions["node-ts.worker-threads"]
    assert workers.kind == "number" and workers.default == 2
    exposure = questions["node-ts.exposure"]
    assert exposure.kind == "choice"
    assert exposure.choices == ["public", "mesh_only"]
    assert exposure.default == "mesh_only"  # financial/broker signals (§M4)
    assert "mesh_only is recommended" in exposure.prompt
    exclusive = questions["node-ts.exclusive-upstream"]
    assert exclusive.kind == "bool" and exclusive.default is True
    assert "alpaca" in exclusive.prompt.lower()


def test_wizard_answers_flow_into_the_manifest_fragment():
    fragment = node_ts.module.manifest_fragment(
        FIXTURE, answers={"node-ts.exposure": "mesh_only"})
    assert fragment["exposure"] == "mesh_only"
    assert fragment["deploy_strategy"] == "recreate"
