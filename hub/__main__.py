"""CLI parity for the scanner (Phase 1 design note item 9): `python -m hub scan <path>`.

Renders the same ScanReport the UI stores — one code path (scanner.core.scan),
two presentations. Deliberately Django-free: static scanning needs no settings,
so the CLI works from any checkout with just the venv.
"""
import argparse
import json
import sys

from scanner import presentation

TIER_ICONS = {"blocker": "✖", "warning": "⚠", "advice": "•", "ok": "✓",
              "pending_sandbox": "▸"}
TIER_ORDER = ["blocker", "warning", "advice", "pending_sandbox", "ok"]


def _render_fields(check, tier):
    """One check's body, per the shared presentation model (R15-ARCH-1).

    WHICH fields, in WHAT order, under WHICH label and hidden at WHICH tiers are read from
    `scanner.presentation` — the same declarations `frontend/src/api/presentation.js` is
    generated from, so this renderer and `CheckBody` cannot disagree about what a check
    says without one of them failing a gate. What stays here is how a TERMINAL says it:
    the indent, the one-path-per-line list, the continuation columns.

    R15-SEC-1: and every repo-controlled string goes through `presentation.safe_*` on the
    way out. This is the boundary where a scan report meets a device that interprets what
    it is given — a committed symlink named `\x1b]0;…\x07` reached the terminal raw
    through the detail line and the refusal list both. `--json` is deliberately NOT
    sanitized: `json.dumps` escapes control characters by construction, and its consumer
    is a parser, not a screen.
    """
    lines = []
    for field in presentation.CHECK_FIELDS:
        if tier in presentation.TIER_GATES.get(field["key"], ()):
            continue
        value = check.get(field["key"])
        if not value:
            continue
        label = field["label"]
        if field["kind"] == "paths":
            # The complete list, one path per line (R14-ARCH-A): the detail's own prose
            # is capped at `_MAX_SKIPPED_REPORTED` because a paragraph is for reading, and
            # this field is the announcement the cap is not allowed to shorten.
            lines.append(f"{presentation.TEXT_INDENT}{label}")
            lines.extend(f"{presentation.TEXT_INDENT}  {presentation.safe_path(p)}"
                         for p in value)
            continue
        body = presentation.text_block(value)
        prefix = f"{label} " if label else ""
        lines.append(f"{presentation.TEXT_INDENT}{prefix}{body}")
    return lines


def render_text(report):
    lines = []
    lines.append(f"modules: {', '.join(report['modules']) or '(no module matched)'}")
    s = report["summary"]
    lines.append("summary: " + "  ".join(
        f"{TIER_ICONS[t]} {t}:{s.get(t, 0)}" for t in TIER_ORDER))
    lines.append("")
    for tier in TIER_ORDER:
        group = [c for c in report["checks"] if c["tier"] == tier]
        if not group:
            continue
        lines.append(f"── {tier.upper()} ({len(group)})")
        for c in group:
            lines.append(f"  {TIER_ICONS[tier]} {c['id']}: {c['title']}")
            lines.extend(_render_fields(c, tier))
        lines.append("")
    draft = report["manifest_draft"]
    svc = (draft["components"] or {}).get("service")
    lines.append("manifest draft: "
                 f"service={svc and svc.get('kind')} "
                 f"strategy={draft['deploy_strategy']} "
                 f"exposure={draft['exposure']} "
                 f"jobs={len(draft['components'].get('jobs', []))} "
                 f"volumes={len(draft['volumes'])}")
    if report["wizard_questions"]:
        lines.append(f"wizard: {len(report['wizard_questions'])} question(s) pending")
    # R16-SEC-1: THE SEAM. Every string this function assembles goes out through one
    # sanitizer, so a field that reaches a terminal is safe because of where it is
    # PRINTED and not because whoever added it remembered a rule.
    #
    # R15-SEC-1 drew the boundary around the check BODY — the fields `_render_fields`
    # renders — and the first title to interpolate a repository's own string walked
    # through it: `node-ts.service-package` names `service_dir.name`, and a monorepo
    # service directory called `svc\x1b]0;PWNED\x07\x1b[2Jx` cleared the operator's
    # screen from the heading line. A per-field opt-in is a rule every future
    # interpolation has to remember, and this one was forgotten by the commit that wrote
    # it.
    #
    # NOT INSTEAD OF THE PER-FIELD POLICY, and the difference is exactly one character:
    # `safe_text` keeps `\n`, because the renderer's own line breaks are structure. A
    # repo-controlled PATH containing a newline would already have been turned into two
    # lines by the time it got here, so `_render_fields` escapes those with `safe_path`
    # BEFORE the list is built. The seam is the backstop; the per-field call is the one
    # place the distinction between prose and a path can still be made.
    return presentation.safe_text("\n".join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hub")
    sub = parser.add_subparsers(dest="cmd", required=True)
    scan_p = sub.add_parser("scan", help="Run the readiness scanner on a project path")
    scan_p.add_argument("path")
    scan_p.add_argument("--json", action="store_true", help="emit the raw ScanReport")
    args = parser.parse_args(argv)

    if args.cmd == "scan":
        from scanner.core import scan

        report = scan(args.path)
        # R15-SEC-2: `ensure_ascii=False` keeps a Chinese path readable in `--json`, and
        # it also emits an undecodable byte's lone surrogate as itself — which no UTF-8
        # stream can encode and which is not valid JSON text. `escape_surrogates` spells
        # exactly those code points the way `ensure_ascii` would have, and leaves every
        # other character alone; the text renderer sanitizes its own output on the way
        # out. Neither path can be taken down by a filename any more.
        print(presentation.escape_surrogates(
                  json.dumps(report, indent=2, ensure_ascii=False)) if args.json
              else render_text(report))
        # Exit 1 on blockers — usable as a CI gate immediately.
        return 1 if report["summary"].get("blocker") else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
