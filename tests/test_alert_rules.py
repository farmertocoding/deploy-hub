"""Alert rules table + classify() (D-037, ALERT-P1-ROWS).

The table is a clause-by-clause transcription of alert-protocol.md §2. An
unregistered kind cannot ship: classify() raises. raise_alert() literals in
the tree must name a registered kind (the AST scan is the ratchet).
"""
import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
PROTOCOL = REPO / "docs" / "plan" / "alert-protocol.md"

_UPDATE_PREFIX = re.compile(
    r"^UPDATE \d{4}-\d{2}-\d{2} \(review3, per §[A-Z0-9]+\):\s*",
    re.I,
)
_SKIP_DIRS = {
    ".git", ".venv", ".venv-scaffold", ".worktrees", "node_modules",
    "frontend", "mutants", "staticfiles", "__pycache__",
}


def _section_2(md):
    start = md.index("## 2. The rules table")
    end = md.index("## 3.")
    return md[start:end]


def _bullets_under(section, header, next_header=None):
    start = section.index(header)
    end = section.index(next_header) if next_header else len(section)
    bullets = []
    for line in section[start:end].splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:])
    return bullets


def protocol_p1_bullets():
    section = _section_2(PROTOCOL.read_text(encoding="utf-8"))
    return _bullets_under(section, "**P1 — wake me:**", "**P2 — today:**")


def _norm(text):
    text = text.replace("**", "")
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = _UPDATE_PREFIX.sub("", text.strip())
    return " ".join(text.split()).casefold()


def _bullet_owns_rule(bullet, rule):
    body, condition = _norm(bullet), _norm(rule.condition_text)
    if not condition:
        return False
    return condition in body or body in condition


def _raise_alert_kind(node):
    """String literal first arg or kind= kwarg; None if the call is not a literal."""
    if node.args:
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
            return arg0.value
    for kw in node.keywords:
        if kw.arg == "kind" and isinstance(kw.value, ast.Constant) and isinstance(
            kw.value.value, str
        ):
            return kw.value.value
    return None


def _call_name(node):
    func = node.func
    return getattr(func, "id", None) or getattr(func, "attr", None)


def _copy(**overrides):
    fields = dict(
        title="alert title",
        body="why this matters to the operator",
        fix_action="do the named fix",
    )
    fields.update(overrides)
    return fields


@pytest.mark.req("ALERT-P1-ROWS")
def test_every_p1_row_of_the_protocol_has_a_rule():
    """Parse §2: each P1 bullet maps to exactly one table row.

    What would make this fail: adding a P1 protocol bullet without a rule,
    dropping a transcribed row, or letting two P1 rows claim the same bullet.
    A missing bullet is a red test, not a comment.
    """
    from monitor.alert_rules import RULES

    bullets = protocol_p1_bullets()
    assert bullets, "parser saw no P1 bullets — the §2 headings moved"
    # §4 kinds (ALERT STORM) are P1 but not §2 bullets — Task 6.
    p1_rules = [
        rule for rule in RULES
        if rule.severity == "p1" and "§2" in rule.source_clause
    ]
    assert len(p1_rules) == len(bullets), (
        f"P1 bullets ({len(bullets)}) and P1 rules ({len(p1_rules)}) drifted: "
        f"bullets={[_norm(b)[:60] for b in bullets]!r} "
        f"kinds={[r.kind for r in p1_rules]!r}"
    )
    claimed = set()
    for bullet in bullets:
        matches = [rule for rule in p1_rules if _bullet_owns_rule(bullet, rule)]
        assert len(matches) == 1, (
            f"P1 bullet must map to exactly one rule, got {len(matches)} "
            f"for {bullet!r}: {[r.kind for r in matches]}"
        )
        claimed.add(matches[0].kind)
    assert claimed == {rule.kind for rule in p1_rules}


def test_every_rule_names_its_protocol_clause():
    """Every row cites the clause it transcribes — no anonymous severities.

    What would make this fail: a row with a blank source_clause, or a clause
    that names neither a § heading nor a decision id.
    """
    from monitor.alert_rules import RULES

    assert RULES, "rules table is empty"
    for rule in RULES:
        clause = (rule.source_clause or "").strip()
        assert clause, f"{rule.kind} has no source_clause"
        assert re.search(r"§|D-\d+", clause), (
            f"{rule.kind} source_clause {clause!r} names no protocol clause"
        )


@pytest.mark.req("ALERT-P1-ROWS")
def test_unknown_kind_raises_unclassified_alert():
    """An unregistered kind cannot ship: classify raises (D-037).

    What would make this fail: classify defaulting unknown kinds to p3, or
    returning None, so a typo ships at the wrong severity.
    """
    from monitor.alert_rules import UnclassifiedAlert, classify

    with pytest.raises(UnclassifiedAlert, match="not-a-registered-kind"):
        classify("not-a-registered-kind")


def test_no_kind_maps_to_two_severities():
    """One kind, one table severity. Escalation is classify() + facts.

    What would make this fail: two rows sharing a kind with different
    severities, so the table itself is ambiguous.
    """
    from monitor.alert_rules import RULES

    seen = {}
    for rule in RULES:
        if rule.kind in seen:
            assert seen[rule.kind] == rule.severity, (
                f"{rule.kind} maps to both {seen[rule.kind]} and {rule.severity}"
            )
        seen[rule.kind] = rule.severity
    assert len(seen) == len(RULES), "duplicate kind rows in the rules table"


def test_staleness_is_p2_and_never_a_restart_trigger():
    """review3 §O1 / §N3: feed data-stale is a P2 push, never a restart.

    What would make this fail: classifying staleness as p1, or marking the
    row restart_trigger=True so a consumer could treat it as a bounce.
    """
    from monitor.alert_rules import RULES, classify

    assert classify("feed-data-stale") == "p2"
    row = next(rule for rule in RULES if rule.kind == "feed-data-stale")
    assert row.restart_trigger is False
    assert row.severity == "p2"


def test_warmup_escalates_to_p1_only_without_a_ready_instance():
    """Warm-up budget is P2; P1 only when facts say no ready instance serves.

    What would make this fail: always returning p1, or ignoring
    ready_instance_serving=False so a site with nothing serving stays P2.
    """
    from monitor.alert_rules import classify

    assert classify("instance-warmup-exceeded") == "p2"
    assert classify("instance-warmup-exceeded", ready_instance_serving=True) == "p2"
    assert classify("instance-warmup-exceeded", ready_instance_serving=False) == "p1"


def test_deadman_post_failure_has_a_row():
    """Phase-3 kind: a failed dead-man POST is a classified row, not an aside.

    What would make this fail: omitting the kind the dead-man path will emit,
    so classify() would raise the first time a POST fails.
    """
    from monitor.alert_rules import RULES, classify

    kinds = {rule.kind for rule in RULES}
    assert "deadman-post-failure" in kinds
    assert classify("deadman-post-failure") == "p2"


@pytest.mark.req("ALERT-P1-ROWS")
def test_every_emitted_kind_in_the_codebase_is_registered():
    """AST scan: every raise_alert( literal kind is a table row.

    What would make this fail: a new raise_alert("typo-kind") call, a
    non-literal kind argument (which would bypass the scan), converting
    _file_scope_finding without registering its kind, or dropping the
    registry call so the scan goes vacuous.
    """
    from monitor.alert_rules import RULES

    registered = {rule.kind for rule in RULES}
    emitted = []
    non_literals = []
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO)
        if set(rel.parts) & _SKIP_DIRS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != "raise_alert":
                continue
            kind = _raise_alert_kind(node)
            if kind is None:
                non_literals.append(f"{rel}:{node.lineno}")
                continue
            emitted.append((str(rel), node.lineno, kind))

    assert non_literals == [], (
        "raise_alert() must take a string-literal kind so the scan can see it: "
        f"{non_literals}"
    )
    missing = sorted({kind for _, _, kind in emitted if kind not in registered})
    assert missing == [], f"emitted kinds not in the rules table: {missing}"

    registry_kinds = [kind for rel, _, kind in emitted if rel == "providers/registry.py"]
    assert registry_kinds, (
        "providers/registry.py::_file_scope_finding must go through raise_alert "
        "(parked Task 1 follow-up) — the scan is otherwise vacuous"
    )
    assert all(kind in registered for kind in registry_kinds)


@pytest.mark.django_db
def test_raise_alert_files_through_finding_at_classified_severity():
    """raise_alert: classify → stable fingerprint → finding().

    What would make this fail: writing Finding rows directly, skipping
    classify, or minting a new fingerprint on every call.
    """
    from core.models import Finding
    from monitor.alerts import raise_alert

    first = raise_alert(
        "cf-token-scope",
        "dns_zone:wall.example",
        fingerprint="cf-scope:1:wall.example",
        source_engine="dns_scope",
        **_copy(
            title="Cloudflare scope verification failed for wall.example",
            body="zone probe returned 2 zones",
            fix_action="Issue a single-zone scoped DNS token",
        ),
    )
    again = raise_alert(
        "cf-token-scope",
        "dns_zone:wall.example",
        fingerprint="cf-scope:1:wall.example",
        source_engine="dns_scope",
        **_copy(
            title="Cloudflare scope verification failed for wall.example",
            body="zone probe returned 2 zones (again)",
            fix_action="Issue a single-zone scoped DNS token",
        ),
    )
    assert first.pk == again.pk
    assert first.fingerprint == "cf-scope:1:wall.example"
    assert first.severity == "p2"
    assert Finding.objects.filter(fingerprint="cf-scope:1:wall.example").count() == 1
    assert again.body == "zone probe returned 2 zones (again)"


@pytest.mark.django_db
def test_after_raise_hook_is_a_passthrough():
    """Task 6 fills after_raise; until then it is identity.

    What would make this fail: raise_alert swallowing the hook, or the
    default hook dropping the Finding.
    """
    import monitor.alerts as alerts

    seen = []
    original = alerts.after_raise

    def _spy(row):
        seen.append(row.pk)
        return row

    alerts.after_raise = _spy
    try:
        row = alerts.raise_alert(
            "deadman-post-failure",
            "hub:deadman",
            fingerprint="deadman:post-failed-hook-test",
            source_engine="monitor.deadman",
            **_copy(title="Dead-man POST failed"),
        )
    finally:
        alerts.after_raise = original

    assert seen == [row.pk]
    assert row.fingerprint == "deadman:post-failed-hook-test"
