"""ACTION_TIERS — the one server↔client friction table (UX-F5 / D-040).

frontend/src/api/action_tiers.js is generated from this module
(`scripts_dev/generate_actions.py`, hooked from `make generate-client`).
Do not put @pytest.mark.req on UX-F5-ACTION-TIERS: the T1 hardware clause
is unbuilt (SCAN-M4).
"""

ACTION_TIERS = (
    {"id": "site.rollback", "tier": "T3", "label": "Roll back", "undo_window_s": 10},
    {"id": "site.restart", "tier": "T3", "label": "Restart", "undo_window_s": 10},
    {"id": "check.rerun", "tier": "T3", "label": "Re-run check", "undo_window_s": 10},
    {"id": "site.deploy", "tier": "T2", "label": "Deploy"},
    {"id": "dns.change", "tier": "T2", "label": "Change DNS"},
    {"id": "site.auto_mode", "tier": "T2", "label": "Toggle auto-mode"},
    {"id": "demo.launch", "tier": "T2", "label": "Launch demo job"},
    {"id": "target.delete", "tier": "T1", "label": "Delete target"},
    {"id": "key.export", "tier": "T1", "label": "Export key"},
    {"id": "kek.rotate", "tier": "T1", "label": "Rotate KEK"},
)
