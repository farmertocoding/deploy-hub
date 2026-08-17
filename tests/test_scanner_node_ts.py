"""node-ts scanner module: §S3 detection, §S4 static checks, and the Q7 fixture
contract — positive pass over sample-node-site plus the MUTATIONS.md negative
matrix (one edit per mutation; exactly the named check flips tier)."""
import json
import os
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


# ── out of round-7 scope, fixed on the round-7 branch ──────────────────────────

def test_a_symlinked_directory_loop_does_not_hang_the_walk(tmp_path):
    """`_iter_source_files` followed symlinked directories, so one link pointing at an
    ancestor was an infinite walk — and it runs during MODULE DETECTION, before any
    check, so an operator scanning a repo with one symlink got a scan that never
    returned. Found by the SRE reviewer while testing loops; not a round-7 finding (this
    function is unchanged in the round's diff), fixed here because it is a real hang.

    `fallbacks._iter_files` already had the treatment — prune symlinked directories,
    `resolve()` into a `seen` set — and this is that treatment, not a second one.

    The consumption is bounded on purpose: `islice` is what makes the RED run of this
    test finish. Unbounded, the failing case does not fail, it hangs, and a test that
    hangs is not evidence of anything."""
    import itertools

    root = tmp_path / "svc"
    (root / "src").mkdir(parents=True)
    (root / "src" / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (root / "src" / "loop").symlink_to(root / "src", target_is_directory=True)
    (root / "sibling").symlink_to(root, target_is_directory=True)

    found = list(itertools.islice(node_ts._iter_source_files(root), 50))
    assert [p.relative_to(root).as_posix() for p in found] == ["src/index.ts"], found


# ── R8-3: a workspace pattern is repo-controlled text handed to a globber ───────


def _workspace_repo(tmp_path, patterns, name="repo"):
    """A minimal node repo whose root package.json declares `patterns`."""
    root = tmp_path / name
    (root / "packages" / "server" / "src").mkdir(parents=True)
    (root / "package.json").write_text(
        json.dumps({"name": "root", "private": True, "workspaces": patterns}) + "\n",
        encoding="utf-8")
    (root / "pnpm-workspace.yaml").write_text(
        "packages:\n" + "".join(f"  - '{p}'\n" for p in patterns), encoding="utf-8")
    (root / "packages/server/package.json").write_text(
        json.dumps({"name": "server", "main": "dist/index.js",
                    "dependencies": {"fastify": "^4.0.0"}}) + "\n", encoding="utf-8")
    (root / "packages/server/src/index.ts").write_text(
        "import Fastify from 'fastify';\n", encoding="utf-8")
    return root


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
@pytest.mark.parametrize("pattern", ["/etc/*", "/*", "C:/Windows/*"])
def test_issue_r8_3_an_absolute_workspace_pattern_does_not_take_the_scan_down(
        tmp_path, pattern):
    """`workspaces` and `packages:` are written by the SCANNED repo and went straight
    into `self.root.glob(pattern)`. pathlib refuses a pattern it calls non-relative by
    RAISING `NotImplementedError`, and `_Survey` is built inside `detect()` — which runs
    for every scan of every framework — so eight characters of JSON in a repo denied a
    scan of itself: exit 1, a traceback, no report.

    Verified before the fix:

        >>> node_ts.NodeTsScannerModule().detect(root)
        NotImplementedError: Non-relative patterns are unsupported

    The scan must complete, and it must SAY the pattern was refused rather than dropping
    it silently — a monorepo whose config names five packages and whose report surveys
    three is a report the operator has no reason to distrust.
    """
    # Declared BESIDE a legitimate pattern, because the property under test is that one
    # refused pattern costs only itself — the entry-level isolation `_read_entry` holds
    # for the other repo-controlled config on this tree.
    root = _workspace_repo(tmp_path, [pattern, "packages/*"],
                           name=f"abs{abs(hash(pattern))}")

    assert node_ts.module.detect(root) is True     # must not raise
    report = core.scan(root)                       # must not raise

    refused = by_id(report, "node-ts.workspace-patterns")
    assert refused["tier"] == "warning"
    assert repr(pattern) in refused["detail"], refused
    assert "absolute" in refused["detail"]
    # …and the packages that ARE inside the tree are still surveyed.
    assert by_id(report, "node-ts.service-package")["tier"] == "ok"


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r8_3_a_workspace_pattern_cannot_read_outside_the_scan_root(tmp_path):
    """The half that does NOT raise, and is the worse of the two: pathlib treats
    `../outside` as a perfectly good relative pattern, `root/../outside` resolves out of
    the tree, the directory is accepted as a workspace package, and `_Survey` reads its
    source files into `all_sources` — which every content check greps and the report
    quotes back.

    Verified before the fix, with the marker file below:

        package_dirs: [.../repo, .../repo/../outside, .../repo/../outside]
        outside content reached the survey: True

    A scan reads the tree it was pointed at. Asserted on the survey AND on the whole
    serialized report, because "the content is not in `all_sources`" and "the content is
    not in the operator's report" are two different claims and only the second is the
    one that matters.
    """
    outer = tmp_path / "outer"
    root = _workspace_repo(outer, ["../outside/*", "packages/*"])
    neighbour = outer / "outside" / "neighbour"
    neighbour.mkdir(parents=True)
    (neighbour / "package.json").write_text(
        json.dumps({"name": "neighbour", "dependencies": {"fastify": "^4.0.0"}}) + "\n",
        encoding="utf-8")
    (neighbour / "leak.ts").write_text(
        'const STOLEN = "MARKER-OUTSIDE-THE-SCAN-ROOT";\n', encoding="utf-8")

    survey = node_ts._Survey(root)

    surveyed = {p.resolve() for p in survey.package_dirs}
    assert surveyed == {root.resolve(), (root / "packages/server").resolve()}, surveyed
    assert neighbour.resolve() not in surveyed
    assert "MARKER-OUTSIDE-THE-SCAN-ROOT" not in survey.all_sources
    assert "neighbour" not in survey.all_sources

    report = core.scan(root)
    assert "MARKER-OUTSIDE-THE-SCAN-ROOT" not in json.dumps(report)
    refused = by_id(report, "node-ts.workspace-patterns")
    assert refused["tier"] == "warning"
    assert "escapes the scanned repository" in refused["detail"]
    assert repr("../outside/*") in refused["detail"]


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r8_3_a_refused_pattern_cannot_write_lines_into_the_report(tmp_path):
    """The pattern is quoted back so the author can find it, which makes it the same
    class of surface `scanner/declarations.py` spends four rounds on: repo-controlled
    text printed as evidence. Quoted through `repr` and bounded, so a newline becomes an
    escape and a 4 KB pattern cannot become the report."""
    forged = "/etc/\nnode-ts.fake-check: everything is fine"
    root = _workspace_repo(tmp_path, [forged, "x" * 200 + "/../*"])

    detail = by_id(core.scan(root), "node-ts.workspace-patterns")["detail"]

    for line in detail.splitlines():
        assert not line.startswith("node-ts.fake-check"), detail
    assert "(truncated)" in detail, detail
    assert "x" * 200 not in detail


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r8_3_an_ordinary_workspace_pattern_is_untouched(tmp_path):
    """The over-correction guard. `packages/*` is how every monorepo on this fleet is
    written, and a validator that refused it would be the noise-for-safety trade that
    round-6b already lost — so the honest case is asserted to produce NO warning at
    all."""
    root = _workspace_repo(tmp_path, ["packages/*"])

    report = core.scan(root)

    assert [c["id"] for c in report["checks"] if c["id"] == "node-ts.workspace-patterns"] == []
    assert "server" in by_id(report, "node-ts.monorepo")["detail"]


# ── F3: the pattern is only half of what the scanned repo controls ─────────────


def _victim_tree(base, marker="VICTIM-TREE-MARKER"):
    """A neighbouring repository, beside the one the operator asked to scan.

    Its one source file carries a `WORKER_THREADS ?? 7` line, which is the reviewer's
    probe: the number is READ BACK OUT of the report as a wizard default, so the test
    can assert that a file outside the scan root steered the answer rather than merely
    that its bytes were opened.
    """
    victim = base / "victim"
    (victim / "src").mkdir(parents=True)
    (victim / "package.json").write_text(json.dumps({"name": "victim"}) + "\n",
                                         encoding="utf-8")
    (victim / "src" / "engine.ts").write_text(
        "const threads = process.env.WORKER_THREADS ?? 7;\n"
        f'const CREDENTIAL = "{marker}";\n', encoding="utf-8")
    return victim


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_f3_a_symlinked_workspace_package_cannot_steer_the_report(tmp_path):
    """The reviewer's probe, verbatim: an ORDINARY pattern plus one committed symlink.

    R8-3 validates the pattern the repo writes; it cannot see what the pattern EXPANDS
    to. `workspaces: ["packages/*"]` passes every one of those rules and then expands to
    whatever `packages/` contains — and git stores symlinks, so `packages/evil ->
    ../../victim` is a committable way to make a neighbouring tree a workspace package.
    `_iter_source_files` refuses to FOLLOW a symlinked directory during its walk, but it
    never questioned the directory handed to it as a base.

    The report is steered, not just read. Before the fix:

        package_dirs: ['repo', 'evil', 'server', 'evil', 'server']
        workspace_names: ['evil', 'server', 'evil', 'server']
        victim marker in all_sources: True
        worker_threads_default: 7 (honest answer: 2)
        wizard node-ts.worker-threads default: 7

    Every regex in this module reads `all_sources`, so the worker default is one of
    many: a `worker_threads` mention flips the worker check from "not detected" to
    "detected", a broker env name arms the financial-signals path, a `ready:` field
    satisfies the readiness pattern for a service that has none.
    """
    _victim_tree(tmp_path)
    root = _workspace_repo(tmp_path, ["packages/*"])
    os.symlink("../../victim", root / "packages" / "evil")

    survey = node_ts._Survey(root)

    assert [p.name for p in survey.package_dirs] == ["repo", "server"], \
        survey.package_dirs
    assert survey.workspace_names() == ["server"]
    assert "VICTIM-TREE-MARKER" not in survey.all_sources
    # The number is the assertion that matters: 2 is this module's own default, 7 exists
    # only in the neighbouring tree.
    assert survey.worker_threads_default() == 2

    report = core.scan(root)
    questions = {q["id"]: q for q in report["wizard_questions"]}
    assert questions["node-ts.worker-threads"]["default"] == 2
    assert "VICTIM-TREE-MARKER" not in json.dumps(report)

    refused = by_id(report, "node-ts.workspace-patterns")
    assert refused["tier"] == "warning"
    assert "is a symlink" in refused["detail"], refused
    assert repr("packages/evil") in refused["detail"], refused


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_f3_a_symlink_pointing_inside_the_root_is_refused_too(tmp_path):
    """The design question, and the stricter reading is the one taken.

    Containment alone would admit `packages/alias -> ../packages/server`, which escapes
    nothing — and is a second name for a directory the survey already has, so it re-reads
    the same sources and double-counts the package. Refusing by WHAT IT IS rather than by
    where it lands also keeps the rule from depending on a link's target, which the repo
    controls and can change between scans.

    `sample-node-site` contains no symlink at all and no repo in the fleet declares a
    workspace through one, so this costs nothing today; the problem line says plainly
    that it was refused for being a link, so a real in-root use produces a report a
    human can act on rather than a silent omission.
    """
    root = _workspace_repo(tmp_path, ["packages/*"])
    os.symlink("server", root / "packages" / "alias")

    survey = node_ts._Survey(root)

    assert [p.name for p in survey.package_dirs] == ["repo", "server"]
    assert any("is a symlink" in problem for problem in survey.workspace_problems), \
        survey.workspace_problems


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_f3_a_real_directory_reached_through_a_symlinked_parent_is_refused(
        tmp_path):
    """Why resolve-containment stays beside the symlink rule instead of being replaced
    by it: `candidate.is_symlink()` is FALSE for `packages/link/pkg` when `link` is the
    symlink and `pkg` is an ordinary directory inside it — and `packages/*/*` is a
    pattern people write."""
    outside = tmp_path / "outside" / "pkg"
    (outside / "src").mkdir(parents=True)
    (outside / "package.json").write_text(json.dumps({"name": "pkg"}) + "\n",
                                          encoding="utf-8")
    (outside / "src" / "x.ts").write_text('const M = "NESTED-VICTIM-MARKER";\n',
                                          encoding="utf-8")
    root = _workspace_repo(tmp_path, ["packages/*/*", "packages/*"])
    os.symlink("../../outside", root / "packages" / "link")

    survey = node_ts._Survey(root)

    assert "NESTED-VICTIM-MARKER" not in survey.all_sources
    assert any("resolves outside" in problem for problem in survey.workspace_problems), \
        survey.workspace_problems


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_f3_a_package_named_by_two_patterns_is_surveyed_once(tmp_path):
    """The duplicate-append half, paired with F3 because it lives in the same three
    lines and is the same class of defect — the survey believing the repo about how many
    packages it has.

    `packages/*` in package.json's `workspaces` and the identical line in
    pnpm-workspace.yaml is the ordinary way a pnpm monorepo is written; both files are
    read and `_find_package_dirs` concatenates their patterns, so the directory was
    appended twice. `workspace_names()` reported `['server', 'server']` — the operator
    is told the monorepo has two packages of the same name — and the package's sources
    were concatenated into `all_sources` an extra time, which doubles the weight of one
    package in every regex that scores across the tree.

    Asserted as an EQUIVALENCE against a repo that names the package once, rather than
    against a source-occurrence count: the root package.json makes the scan root itself
    a package dir whose walk already covers its children, so `all_sources` legitimately
    contains each file more than once. That overlap is pre-existing and is a separate
    question; what this pins is that naming a package twice changes nothing.
    """
    twice = _workspace_repo(tmp_path, ["packages/*"], name="twice")
    assert "packages/*" in (twice / "pnpm-workspace.yaml").read_text(encoding="utf-8")
    assert "packages/*" in (twice / "package.json").read_text(encoding="utf-8")

    once = _workspace_repo(tmp_path, ["packages/*"], name="once")
    once_pkg = json.loads((once / "package.json").read_text(encoding="utf-8"))
    del once_pkg["workspaces"]
    (once / "package.json").write_text(json.dumps(once_pkg) + "\n", encoding="utf-8")

    twice_survey, once_survey = node_ts._Survey(twice), node_ts._Survey(once)

    assert [p.name for p in twice_survey.package_dirs] == ["twice", "server"]
    assert twice_survey.workspace_names() == once_survey.workspace_names() == ["server"]
    assert twice_survey.all_sources == once_survey.all_sources
    assert twice_survey.workspace_problems == []

    mono = by_id(core.scan(twice), "node-ts.monorepo")
    assert mono["detail"].count("server") == 1, mono["detail"]


# ── round-9 queue item 1: the pattern was half of it, the FILE is the other half ─


def _single_package_repo(tmp_path, name="repo"):
    """A minimal single-package node repo — no workspaces, nothing exotic.

    Deliberately NOT `_workspace_repo`: the file-level escape needs no monorepo, no
    workspace pattern and no `..` anywhere in the repo's own configuration. An ordinary
    repo plus one committed symlink is the whole setup.
    """
    root = tmp_path / name
    (root / "src").mkdir(parents=True)
    (root / "package.json").write_text(
        json.dumps({"name": name, "main": "dist/index.js",
                    "engines": {"node": "22.x"},
                    "dependencies": {"fastify": "^4.0.0"}}) + "\n", encoding="utf-8")
    (root / "src" / "index.ts").write_text(
        "import Fastify from 'fastify';\n"
        "const threads = process.env.WORKER_THREADS ?? 2;\n", encoding="utf-8")
    return root


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r9_1_a_symlinked_source_file_cannot_steer_the_report(tmp_path):
    """F3 refused the symlinked workspace BASE; the files inside the tree were still
    read through whatever they pointed at.

    `_iter_source_files` has refused to FOLLOW a symlinked directory since round 7, and
    the round-7 comment says symlinked FILES are still read — a rationale borrowed from
    `fallbacks`, where a committed symlinked `.env` is exactly what the secret suite is
    hunting. In node-ts the content does not get looked at, it STEERS: every regex in
    the module reads `all_sources`, so one committed link is enough.

        src/evil.ts -> ../../victim/engine.ts

    No workspace, no pattern, no `..` in any file the repo commits — a `..` inside a
    symlink target is not a path the R8-3 rules ever see.
    """
    _victim_tree(tmp_path)
    root = _single_package_repo(tmp_path)
    os.symlink("../../victim/src/engine.ts", root / "src" / "evil.ts")

    survey = node_ts._Survey(root)

    assert "VICTIM-TREE-MARKER" not in survey.all_sources
    assert "VICTIM-TREE-MARKER" not in survey.service_text()
    # 2 is the repo's own line; 7 exists only in the neighbouring tree.
    assert survey.worker_threads_default() == 2

    report = core.scan(root)
    assert "VICTIM-TREE-MARKER" not in json.dumps(report)
    questions = {q["id"]: q for q in report["wizard_questions"]}
    assert questions["node-ts.worker-threads"]["default"] == 2

    refused = by_id(report, "node-ts.symlinked-files")
    assert refused["tier"] == "warning"
    assert "resolves outside the scan root" in refused["detail"], refused
    assert repr("src/evil.ts") in refused["detail"], refused


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r9_1_a_symlinked_package_json_cannot_steer_the_report(tmp_path):
    """The same route through the manifest reads rather than the source walk.

    A package.json outside the tree decides more of the report than a source file does:
    its `dependencies` land in `all_deps`, where `ccxt` ARMS three ingestion checks that
    would otherwise not run at all, and its `engines`/`main` are read back out as the
    engines pin and the compiled-JS verdict for a package whose real manifest says
    something else.
    """
    outside = tmp_path / "victim"
    outside.mkdir()
    (outside / "package.json").write_text(
        json.dumps({"name": "LEAKED-PACKAGE-NAME", "main": "src/index.ts",
                    "engines": {"node": "18.x"},
                    "dependencies": {"ccxt": "^4.0.0"}}) + "\n", encoding="utf-8")

    root = _workspace_repo(tmp_path, ["packages/*"])
    (root / "packages/server/package.json").unlink()
    os.symlink("../../../victim/package.json", root / "packages/server/package.json")

    survey = node_ts._Survey(root)

    assert survey.packages[root / "packages" / "server"] == {}
    assert "ccxt" not in survey.all_deps
    assert not survey.ingestion_armed()

    report = core.scan(root)
    assert "LEAKED-PACKAGE-NAME" not in json.dumps(report)
    assert [c["id"] for c in report["checks"] if c["id"].startswith("node-ts.ingest")] == []

    refused = by_id(report, "node-ts.symlinked-files")
    assert "resolves outside the scan root" in refused["detail"], refused
    assert repr("packages/server/package.json") in refused["detail"], refused


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r9_1_a_scan_root_reached_through_a_symlink_is_read_normally(tmp_path):
    """The false positive the containment rule exists to avoid, at file level.

    F3's directory rule resolves BOTH sides for this reason and the file rule inherits
    it: a scan root is frequently reached THROUGH a symlink (`/tmp` on macOS, a checkout
    under a linked home), so every source file in such a tree resolves to a path that
    does not start with the root as spelled. Compare unresolved root against resolved
    file and the scanner refuses to read a single line of an entirely ordinary repo.
    """
    real = _single_package_repo(tmp_path / "real")
    linked_root = tmp_path / "linked-repo"
    os.symlink(real, linked_root, target_is_directory=True)

    survey = node_ts._Survey(linked_root)

    assert "import Fastify" in survey.all_sources
    assert survey.symlink_problems == []
    assert survey.packages[linked_root].get("name") == "repo"
    assert [c["id"] for c in core.scan(linked_root)["checks"]
            if c["id"] == "node-ts.symlinked-files"] == []


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r9_1_an_in_root_symlinked_file_is_still_read(tmp_path):
    """And the case the rule deliberately does NOT refuse — which is where node-ts parts
    company with F3's directory rule, not by accident.

    F3 refuses a symlinked workspace BASE even when it points inside the root, because a
    second NAME for a package the survey already has double-counts it. A file link is
    not that: `src/config.ts -> ../shared/config.ts` and a `package.json` linked from a
    shared config directory are ordinary committed layouts, the content is inside the
    tree the operator pointed at either way, and refusing them would drop real source
    out of the report to no end. Containment is the whole test — refuse where it lands,
    not what it is.
    """
    root = _single_package_repo(tmp_path)
    (root / "shared").mkdir()
    (root / "shared" / "config.ts").write_text(
        'export const IN_ROOT_MARKER = "IN-ROOT-MARKER";\n', encoding="utf-8")
    os.symlink("../shared/config.ts", root / "src" / "config.ts")

    survey = node_ts._Survey(root)

    assert "IN-ROOT-MARKER" in survey.all_sources
    assert survey.symlink_problems == []
    assert [c["id"] for c in core.scan(root)["checks"]
            if c["id"] == "node-ts.symlinked-files"] == []


# ── round-9 queue item 3: the candidate that died before the refusal ────────────


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r9_3_a_dangling_workspace_symlink_is_refused_out_loud(tmp_path):
    """`packages/gone -> ../../removed`, which is what a workspace looks like after
    somebody deletes the tree it pointed at (or checks the repo out on a machine where
    that tree never existed).

    The R8-3/F3 rule is refuse and say so, and this candidate said nothing: a broken
    link fails `candidate.is_dir()` on the line ABOVE `_workspace_candidate_problem`, so
    the pattern the repo declared expanded to a package the survey silently dropped —
    the exact "config names five packages, report surveys four" reading the problem
    channel exists to prevent.
    """
    root = _workspace_repo(tmp_path, ["packages/*"])
    os.symlink("../../removed", root / "packages" / "gone")

    survey = node_ts._Survey(root)

    assert [p.name for p in survey.package_dirs] == ["repo", "server"]
    assert any("gone" in problem for problem in survey.workspace_problems), \
        survey.workspace_problems

    refused = by_id(core.scan(root), "node-ts.workspace-patterns")
    assert refused["tier"] == "warning"
    assert repr("packages/gone") in refused["detail"], refused


# ── round-9 item 1, second pass: the reads that never went through the walk ─────


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r9_1_a_symlinked_env_example_cannot_arm_the_financial_path(tmp_path):
    """The escape the first pass's own comment names, still live through a FIXED-NAME
    read: "a broker env name that arms the financial-signals path".

    `.env.example` is not a source file and not a manifest, so neither `_iter_sources`
    nor `_read_package_json` ever saw it — it was read straight off `self.root` by name.
    One committed link is enough, and the steer is the sharpest in the module: the
    neighbour's broker env names arm `financial_signals()`, which flips the wizard's
    exposure default from `public` to `mesh_only` and rewrites the prompt to tell the
    operator this service "appears to handle financial/broker data". A recommendation
    about somebody else's repository, echoed back with the neighbour's variable names in
    the `node-ts.secrets-env` detail.
    """
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "env.example").write_text(
        "BINANCE_API_KEY=\nBINANCE_API_SECRET=\n", encoding="utf-8")

    root = _single_package_repo(tmp_path)
    os.symlink("../victim/env.example", root / ".env.example")

    survey = node_ts._Survey(root)

    assert survey.env_example == ""
    assert survey.broker_env_names() == []
    assert not survey.financial_signals()

    report = core.scan(root)
    assert "BINANCE" not in json.dumps(report)
    questions = {q["id"]: q for q in report["wizard_questions"]}
    assert questions["node-ts.exposure"]["default"] == "public"

    refused = by_id(report, "node-ts.symlinked-files")
    assert repr(".env.example") in refused["detail"], refused


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r9_1_a_symlinked_tsconfig_cannot_vouch_for_strict_mode(tmp_path):
    """The same class pointing the other way, and that direction is why containment on
    a config read is not cosmetic.

    Every escape demonstrated so far ADDS a finding — a worker count, an armed check, a
    broker warning. This one REMOVES one: a link to a neighbouring `tsconfig.json` with
    `"strict": true` turns `node-ts.strict-build` from a warning into `ok`, so the report
    vouches for strict mode this repository does not have and the operator has been told
    the thing that makes `tsc --noEmit` a real gate is on.
    """
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"strict": True}}) + "\n", encoding="utf-8")

    root = _single_package_repo(tmp_path)
    os.symlink("../victim/tsconfig.json", root / "tsconfig.json")

    strict = by_id(core.scan(root), "node-ts.strict-build")

    assert strict["tier"] == "warning", strict
    assert "strict" in strict["title"].lower()

    refused = by_id(core.scan(root), "node-ts.symlinked-files")
    assert repr("tsconfig.json") in refused["detail"], refused


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r9_1_the_remaining_fixed_name_reads_are_contained_too(tmp_path):
    """`pnpm-workspace.yaml` and `pyproject.toml`, same class and lower impact — the
    first decides which packages exist, the second co-detects the §N7 offline component
    and puts `node-ts.jobs-image` in the report. Fixed in the same commit because
    "route every fixed-name read through the containment rule" is a smaller thing to
    review, and to keep true, than four sites with three of them done.
    """
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "pnpm-workspace.yaml").write_text(
        "packages:\n  - 'packages/*'\n", encoding="utf-8")
    (victim / "pyproject.toml").write_text(
        '[project]\ndependencies = ["duckdb>=1.0"]\n', encoding="utf-8")

    root = _single_package_repo(tmp_path)
    os.symlink("../victim/pnpm-workspace.yaml", root / "pnpm-workspace.yaml")
    os.symlink("../victim/pyproject.toml", root / "pyproject.toml")

    survey = node_ts._Survey(root)

    assert survey.offline_deps == []
    assert survey.package_dirs == [root]

    report = core.scan(root)
    assert [c["id"] for c in report["checks"] if c["id"] == "node-ts.jobs-image"] == []
    detail = by_id(report, "node-ts.symlinked-files")["detail"]
    assert repr("pnpm-workspace.yaml") in detail, detail
    assert repr("pyproject.toml") in detail, detail


# ── R10-Q1 audit: the same OSError-only guard, in this module ──────────────────
#
# `escapes_root` was the finding; `_symlink_escape_problem` is the sibling the finding
# asked to be audited. It resolves both sides itself, inside its own `except OSError`,
# to compose the "could not be resolved" wording — so on a symlink loop it raised
# `RuntimeError` out of `_Survey.__init__`, which runs inside `detect()`.

@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r10_q1_a_looping_fixed_name_link_is_refused_rather_than_raised(tmp_path):
    """R10-Q1, node-ts half. `.env.example -> .env.example`, which is the read this
    module calls its sharpest steer — the broker env names it carries rewrite the
    exposure question and flip its default. It is read by NAME, unconditionally, so the
    loop reaches the rule rather than dying at an `is_file()` gate the way a looping
    source file does. The survey names it as unresolvable and reads nothing, which is
    what the refusal channel exists to say.
    """
    root = _single_package_repo(tmp_path)
    os.symlink(".env.example", root / ".env.example")

    survey = node_ts._Survey(root)

    assert ".env.example" in "; ".join(survey.symlink_problems)
    assert survey.env_example == ""
    report = core.scan(root)
    assert by_id(report, "node-ts.symlinked-files")["tier"] == "warning"
