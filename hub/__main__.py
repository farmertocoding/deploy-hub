"""CLI parity for the scanner (Phase 1 design note item 9): `python -m hub scan <path>`.

Renders the same ScanReport the UI stores — one code path (scanner.core.scan),
two presentations. Deliberately Django-free: static scanning needs no settings,
so the CLI works from any checkout with just the venv.
"""
import argparse
import json
import sys

TIER_ICONS = {"blocker": "✖", "warning": "⚠", "advice": "•", "ok": "✓",
              "pending_sandbox": "▸"}
TIER_ORDER = ["blocker", "warning", "advice", "pending_sandbox", "ok"]


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
            if c["detail"]:
                lines.append(f"      {c['detail']}")
            # R14-ARCH-A: the refusal list, ALL of it, one path per line.
            #
            # `core.symlinked-files`' detail prints ten paths and counts the rest, because
            # a report line is for reading (`_MAX_SKIPPED_REPORTED`). `refused_paths` is
            # the complete announcement — R12-A1 added it so the FACT would not be the
            # prose — and this renderer printed the prose and stopped. On a tree with
            # fourteen escaping links the CLI told the operator "… and 4 more" and gave
            # them no way to learn which four: the four appeared in no line of its output.
            # `CheckBody` in the UI has rendered all of them since R12-ARCH-1, so the two
            # presentations of one report disagreed about what the report said, in the
            # file whose docstring claims "one code path, two presentations".
            #
            # The prose cap stays exactly as it is. The cap is a reading decision about a
            # paragraph; this is the list, and the list is why the field exists.
            for path in c.get("refused_paths") or ():
                lines.append(f"        {path}")
            if c["fix_hint"] and tier in ("blocker", "warning"):
                lines.append(f"      fix: {c['fix_hint']}")
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
    return "\n".join(lines)


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
        print(json.dumps(report, indent=2, ensure_ascii=False) if args.json
              else render_text(report))
        # Exit 1 on blockers — usable as a CI gate immediately.
        return 1 if report["summary"].get("blocker") else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
