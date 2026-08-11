"""node-ts scanner module: §S3 detection, §S4 static checks, and the Q7 fixture
contract — positive pass over sample-node-site plus the MUTATIONS.md negative
matrix (one edit per mutation; exactly the named check flips tier)."""
import json
import pathlib
import shutil
from typing import NamedTuple

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
    # the offline pyproject (manual-v1) does not mask the committed pnpm lock.
    # "manual-v1" in the detail pins that the module's SUPERSEDING result survived
    # registry composition (D-010) — the generic core result would warn here, since
    # sample-node-site's root pyproject.toml has no lock of its own.
    assert tiers["core.lockfile"] == "ok"
    assert "manual-v1" in by_id(pristine_report, "core.lockfile")["detail"]


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


def test_issue_r4_11_a_node_ts_scan_surfaces_the_exposure_auth_check(tmp_path):
    """R4-11 WI-3: SCAN-M4-EXPOSURE-AUTH says *both modules* warn when no
    authentication is detected. Nothing asserted that a scan of a node-ts tree
    carries `core.exposure-auth` at all — the two marked tests called
    `fallbacks.common_checks` directly. This pins the node-ts half.

    Asserted at REPORT level (D-010): since the core suite is composed by
    `core.scan` rather than by each module, `module.checks()` is deliberately
    core-free and the report is where the requirement's claim actually lives.

    Deliberately unmarked: the requirement stays waived (WAIVERS.md) — the
    blocker escalation does not exist, so no single test can honestly carry the
    marker yet. This test is named in the waiver as the node-ts half of the proof.
    """
    res = by_id(core.scan(FIXTURE), "core.exposure-auth")
    assert res["tier"] == "warning"
    assert "no authentication detected" in res["detail"]

    # …and it silences when the tree does carry an auth indicator.
    site = copy_fixture(tmp_path)
    (site / "packages" / "server" / "src" / "auth.ts").write_text(
        "export function login(req: Request) { return null; }\n", encoding="utf-8")
    assert by_id(core.scan(site), "core.exposure-auth")["tier"] == "ok"


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


def mutate_unsurface_feed_age(site):  # MUTATIONS.md #10
    """Stop /healthz reporting the feed-age metric: rename it out of the payload.

    One identifier rename, applied at its definition and its single call site so
    the fixture still compiles (MUTATIONS.md "one edit" rule). Note the check
    greps the concatenated text of *every* service file that mentions healthz, so
    editing only the payload in index.ts leaves ingest.ts's `lastTickAgeS`
    matching — the reason a one-file edit cannot express this negative.
    """
    for path in (site / SERVER_INDEX, site / SERVER_INGEST):
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("feed_age", "tick_gap")
                            .replace("lastTickAgeS", "tickGapS"), encoding="utf-8")


def mutate_unbounded_backfill(site):  # MUTATIONS.md #11
    """Drop the bounded-concurrency wording/const from the backfill path."""
    path = site / SERVER_INGEST
    text = path.read_text(encoding="utf-8")
    assert "CONCURRENCY" in text and "concurrency" in text
    path.write_text(text.replace("CONCURRENCY", "PARALLELISM").replace("concurrency",
                                                                      "parallelism"),
                    encoding="utf-8")


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
    # R4-11 WI-8: the two behavioural checks that had no negative case at all.
    ("unsurface_feed_age", mutate_unsurface_feed_age, "node-ts.ingest-staleness",
     "warning"),
    ("unbounded_backfill", mutate_unbounded_backfill, "node-ts.ingest-backfill",
     "advice"),
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

# Where each `node-ts.*` check's negative case is proven. The matrix rows above cover
# the checks whose negative is a tier flip; the rest are recordings whose negative is
# the other branch of the message (or the check's absence) and are proven by the
# minimal-tree test below. Q7-NODE-FIXTURE says "a mutation set asserting EACH check's
# negative case" — before R4-11 WI-8, seven checks had no entry here at all.
class _Owner(NamedTuple):
    """Who proves one check's negative case, in a form a test can *resolve*.

    R4-11 F-3: these values used to be prose — `"MUTATIONS #10"` — that nothing ever
    cross-checked against the real `MUTATIONS` list. Deleting the `unsurface_feed_age`
    row left `node-ts.ingest-staleness` pointing at a matrix entry that no longer
    existed, and both enforcement tests below stayed green: the map recorded an
    intention, not a fact. `ref` now names the thing that does the proving, and the
    enforcement test resolves every one of them.

    The MUTATIONS.md table numbering lives on the `mutate_*` functions above, one per
    row, so the fixture contract is still one grep away from the row name.
    """

    kind: str   # "matrix" | "branch" | "test"
    ref: str    # MUTATIONS row name | branch-test name | test function name


def _matrix(row_name):
    """Negative case is the named row of the `MUTATIONS` matrix (a tier flip)."""
    return _Owner("matrix", row_name)


def _named_test(func_name):
    """Negative case is a standalone test in this module (predates the matrix)."""
    return _Owner("test", func_name)


_BRANCH_TEST = _Owner(
    "branch", "test_issue_r4_11_detection_recordings_have_their_negative_branch")

# The checks whose negative case is the other branch of a message (or the check being
# absent) rather than a tier flip, so they cannot live in the single-edit MUTATIONS
# matrix. `test_issue_r4_11_detection_recordings_have_their_negative_branch` iterates
# THIS constant and demands an assertion block per id — a check cannot be listed as
# branch-owned while its branch goes unasserted, which is the other half of F-3:
# before it, deleting an assertion from that test lost a negative case silently.
_CORE_MATRIX_TARGETS = frozenset({"core.lockfile", "core.secret-scan"})
"""The common-core checks the Q7 fixture contract carries a mutation for (MUTATIONS.md
#5 and #6). They are not `node-ts.*` checks so they have no `NEGATIVE_CASE_OWNER` entry
— pinned separately, because otherwise "removing any MUTATIONS row goes red" would hold
for nine rows and quietly not for these two."""

_BRANCH_TEST_CHECKS = frozenset({
    "node-ts.monorepo",
    "node-ts.service-package",
    "node-ts.recognized-deps",
    "node-ts.worker-threads",
    "node-ts.offline-component",
    "node-ts.jobs-image",
    "node-ts.exclusive-upstream",
    "node-ts.local-state",
    "node-ts.secrets-env",
})

NEGATIVE_CASE_OWNER = {
    "node-ts.strict-build": _matrix("strict_false"),
    "node-ts.graceful-shutdown": _matrix("remove_sigterm"),
    "node-ts.readiness-pattern": _matrix("remove_ready_gate"),
    "node-ts.ws-heartbeat": _matrix("remove_heartbeat"),
    "node-ts.ingest-reconnect": _matrix("remove_reconnect_backoff"),
    "node-ts.compiled-js": _matrix("ts_node_start"),
    "node-ts.engines-pin": _matrix("remove_engines"),
    "node-ts.ingest-staleness": _matrix("unsurface_feed_age"),
    "node-ts.ingest-backfill": _matrix("unbounded_backfill"),
    "node-ts.bun-dev-only": _named_test("test_bun_in_the_runtime_path_is_flagged"),
    "node-ts.fastify-serving": _named_test(
        "test_missing_trust_proxy_flags_fastify_serving"),
    # Listed one by one rather than spread from _BRANCH_TEST_CHECKS: the equality
    # assertion below is only worth running if the two are written independently.
    "node-ts.monorepo": _BRANCH_TEST,
    "node-ts.service-package": _BRANCH_TEST,
    "node-ts.recognized-deps": _BRANCH_TEST,
    "node-ts.worker-threads": _BRANCH_TEST,
    "node-ts.offline-component": _BRANCH_TEST,
    "node-ts.jobs-image": _BRANCH_TEST,
    "node-ts.exclusive-upstream": _BRANCH_TEST,
    "node-ts.local-state": _BRANCH_TEST,
    "node-ts.secrets-env": _BRANCH_TEST,
}


@pytest.mark.req("Q7-NODE-FIXTURE")
def test_issue_r4_11_every_node_ts_check_has_a_negative_case():
    """The "each check" scope of the requirement, made mechanical — in both directions.

    Adding a 21st check leaves the requirement reading `verified` on a mutation set
    that never touches it (the gap the R4-11 audit found); *removing* a negative case
    does the same thing more quietly, because nothing was deleted from the inventory —
    which is R4-11 F-3. So the owner map is checked against the real `MUTATIONS` list
    and the real test functions, not read as documentation.
    """
    assert set(NEGATIVE_CASE_OWNER) == set(EXPECTED_TIERS), (
        f"owner map and check inventory disagree: "
        f"no negative case for {sorted(set(EXPECTED_TIERS) - set(NEGATIVE_CASE_OWNER))}, "
        f"stale entries for {sorted(set(NEGATIVE_CASE_OWNER) - set(EXPECTED_TIERS))}")

    matrix_rows = {name: target for name, _mutate, target, _tier in MUTATIONS}
    assert len(matrix_rows) == len(MUTATIONS), "duplicate row names in MUTATIONS"

    # Every matrix row must name a check the fixture actually produces.
    matrix_targets = {t for t in matrix_rows.values() if not t.startswith("core.")}
    unknown = sorted(matrix_targets - set(EXPECTED_TIERS))
    assert unknown == [], f"MUTATIONS rows target unknown checks: {unknown}"
    assert {t for t in matrix_rows.values() if t.startswith("core.")} \
        == set(_CORE_MATRIX_TARGETS), "the fixture's common-core mutation rows changed"

    # A claim of a matrix row resolves to a row that exists AND targets this check.
    for check_id, owner in sorted(NEGATIVE_CASE_OWNER.items()):
        if owner.kind != "matrix":
            continue
        assert matrix_rows.get(owner.ref) == check_id, (
            f"{check_id} claims MUTATIONS row {owner.ref!r}, which "
            + (f"targets {matrix_rows[owner.ref]}" if owner.ref in matrix_rows
               else "does not exist — the row was removed and the claim was not"))

    # ...and the other direction, so a row cannot cover a check nobody credited to it.
    claimed_by_matrix = {check_id for check_id, owner in NEGATIVE_CASE_OWNER.items()
                         if owner.kind == "matrix"}
    assert claimed_by_matrix == matrix_targets, (
        f"matrix rows exist for {sorted(matrix_targets - claimed_by_matrix)} but no "
        f"check credits them; {sorted(claimed_by_matrix - matrix_targets)} credit a "
        f"matrix row that is gone")

    # Test-owned claims must name a test that exists here — a rename or deletion is a
    # lost negative case exactly like a deleted matrix row.
    for check_id, owner in sorted(NEGATIVE_CASE_OWNER.items()):
        if owner.kind == "matrix":
            continue
        func = globals().get(owner.ref)
        assert owner.ref.startswith("test_") and callable(func), (
            f"{check_id}'s negative case names {owner.ref!r}, which is not a test "
            f"function in this module")

    # The branch-owned entries and the constant the branch test iterates are one list.
    assert {check_id for check_id, owner in NEGATIVE_CASE_OWNER.items()
            if owner.kind == "branch"} == set(_BRANCH_TEST_CHECKS)


@pytest.mark.req("Q7-NODE-FIXTURE")
def test_issue_r4_11_detection_recordings_have_their_negative_branch(tmp_path):
    """R4-11 WI-8: five §S3 recording checks had no negative case anywhere.

    `node-ts.monorepo`, `recognized-deps` and `worker-threads` are always `ok` —
    their negative is the *other branch* of the message, not a tier flip, so they
    cannot live in the single-edit MUTATIONS matrix (which asserts a tier change).
    `offline-component`'s negative is the check being absent, and
    `service-package`'s is a real `warning`. One minimal tree exercises all five:
    a single-package project, detected only by its serverish `main`, with no
    recognized dependency, no worker threads, no pyproject.toml, and no server
    framework dependency to make it a deployable service.

    R4-11 F-3: the assertions are registered per check id and then driven from
    `_BRANCH_TEST_CHECKS`, so deleting a check's block fails the coverage assertion
    rather than quietly shrinking what "proven by the branch test" covers. Before
    this, dropping the `worker-threads` line left the owner map still claiming this
    test proves it — with nothing here that did.
    """
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "solo", "main": "dist/index.js",
        "scripts": {"build": "tsc -p ."},
    }))
    src = tmp_path / "src"
    src.mkdir()
    (src / "index.ts").write_text("export const noop = () => undefined;\n")

    assert node_ts.module.detect(tmp_path) is True  # serverish main alone detects
    checks = {c.id: c for c in node_ts.module.checks(tmp_path)}

    negatives = {}

    def negative(check_id):
        def register(fn):
            negatives[check_id] = fn
            return fn
        return register

    @negative("node-ts.monorepo")
    def _monorepo():
        assert checks["node-ts.monorepo"].title == "Single-package Node project"
        assert "No pnpm-workspace.yaml" in checks["node-ts.monorepo"].detail

    @negative("node-ts.service-package")
    def _service_package():
        assert checks["node-ts.service-package"].tier == "warning"
        assert "No workspace package has a server framework dependency" in \
            checks["node-ts.service-package"].detail

    @negative("node-ts.recognized-deps")
    def _recognized_deps():
        assert "(none)" in checks["node-ts.recognized-deps"].detail
        assert "ingestion-daemon checks armed" not in \
            checks["node-ts.recognized-deps"].detail

    @negative("node-ts.worker-threads")
    def _worker_threads():
        assert checks["node-ts.worker-threads"].title.endswith("not detected")

    @negative("node-ts.offline-component")
    def _offline_component():
        assert "node-ts.offline-component" not in checks

    @negative("node-ts.jobs-image")
    def _jobs_image():
        assert "node-ts.jobs-image" not in checks  # no offline component ⇒ no image

    # The three checks that fire at a non-ok tier on the pristine fixture have their
    # quiet branch here — the same "negative case" obligation, mirrored.
    @negative("node-ts.exclusive-upstream")
    def _exclusive_upstream():
        assert checks["node-ts.exclusive-upstream"].tier == "ok"

    @negative("node-ts.local-state")
    def _local_state():
        assert checks["node-ts.local-state"].tier == "ok"

    @negative("node-ts.secrets-env")
    def _secrets_env():
        assert checks["node-ts.secrets-env"].tier == "ok"

    assert set(negatives) == set(_BRANCH_TEST_CHECKS), (
        f"branch-owned checks with no assertion here: "
        f"{sorted(set(_BRANCH_TEST_CHECKS) - set(negatives))}; "
        f"asserted here but not branch-owned: "
        f"{sorted(set(negatives) - set(_BRANCH_TEST_CHECKS))}")
    for check_id in sorted(_BRANCH_TEST_CHECKS):
        negatives[check_id]()


@pytest.mark.req("Q7-NODE-FIXTURE")
def test_bun_in_the_runtime_path_is_flagged(tmp_path, pristine_report):
    assert by_id(pristine_report, "node-ts.bun-dev-only")["tier"] == "ok"
    site = copy_fixture(tmp_path)  # bun as devDependency/test script is fine
    edit_json(site / SERVER_PKG,
              lambda d: d["scripts"].__setitem__("start", "bun src/index.ts"))
    checks = {c.id: c for c in node_ts.module.checks(site)}
    assert checks["node-ts.bun-dev-only"].tier == "warning"
    assert "bun" in checks["node-ts.bun-dev-only"].detail


@pytest.mark.req("Q7-NODE-FIXTURE")
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
