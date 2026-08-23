"""ACTION_TIERS — the one server↔client friction table (UX-F5 / D-040).

frontend/src/api/action_tiers.js is generated from this module
(`scripts_dev/generate_actions.py`, hooked from `make generate-client`).
T1 hardware touch is proven under SEC-F5-T1-HARDWARE-TOUCH; the full-text
UX-F5-ACTION-TIERS marker lives on those tests, not this module.
"""

ACTION_TIERS = (
    {"id": "site.rollback", "tier": "T3", "label": "Roll back", "undo_window_s": 10},
    {"id": "site.restart", "tier": "T3", "label": "Restart", "undo_window_s": 10},
    {"id": "check.rerun", "tier": "T3", "label": "Re-run check", "undo_window_s": 10},
    {"id": "site.deploy", "tier": "T2", "label": "Deploy"},
    {"id": "dns.change", "tier": "T2", "label": "Change DNS"},
    {"id": "site.auto_mode", "tier": "T2", "label": "Toggle auto-mode"},
    {"id": "site.adopt.start", "tier": "T2", "label": "Start adopt"},
    {"id": "site.adopt.cancel", "tier": "T2", "label": "Cancel adopt"},
    {"id": "demo.launch", "tier": "T2", "label": "Launch demo job"},
    {"id": "target.delete", "tier": "T1", "label": "Delete target"},
    {"id": "key.export", "tier": "T1", "label": "Export key"},
    {"id": "kek.rotate", "tier": "T1", "label": "Rotate KEK"},
    {"id": "ssh.rotate", "tier": "T1", "label": "Rotate SSH key"},
    {"id": "instance.create", "tier": "T1", "label": "Create target"},
    {"id": "instance.terminate", "tier": "T1", "label": "Terminate target"},
    {"id": "partner.create", "tier": "T1", "label": "Create partner"},
    {"id": "partner.suspend", "tier": "T1", "label": "Suspend partner"},
    {"id": "partner.api_kill_switch", "tier": "T1", "label": "Disable partner API"},
    {"id": "partner.site_takedown", "tier": "T2", "label": "Take down site"},
    {"id": "partner.destination_rank", "tier": "T2", "label": "Rank partner destination"},
)
