"""Pinned Phase 6 propose-mode thresholds and copy (design note §2)."""

MEM_PCT_THRESHOLD = 85.0
CONSECUTIVE_MINUTES = 5
WINDOW_S = 300
MAX_SAMPLE_GAP_S = 120
OVERFLOW_HOURLY_USD = "0.0416"
OVERFLOW_SIZE = "t3.medium"
PROPOSE_MODE = "propose"
FIX_ACTION = "Ack is not launch. Propose-mode does not launch."
TITLE = "Scale-out proposal awaiting approval (propose mode)"
