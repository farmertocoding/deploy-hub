# Alert Protocol — how the system tells Joseph something went wrong

**Project:** web deploy automation & monitor · Expands `plan-addendum-2026-07-30.md` §C5 into the operating protocol.
**Principle:** for a solo operator, over-alerting is as fatal as under-alerting — after the tenth 3 a.m. "disk 85%" email you filter the sender, then miss the real outage. So: **few channels, hard rules, everything else digested.**

---

## 1. The three severities — and the only three delivery behaviors

| Severity | Meaning | Delivery | Repeats |
|---|---|---|---|
| **P1 — WAKE ME** | A prod site or the platform itself is failing *now*, or money/security is bleeding | **Phone push (ntfy)**, max-priority with sound/vibrate override + email copy | Re-pushed **hourly until acknowledged**; unacked 24 h → also email with `[UNACKED]` |
| **P2 — TODAY** | Degrading or risky, but nothing is down; fix within the day | Phone push, normal priority (respects phone quiet hours), batched: >1 P2 in 10 min = one grouped push | Once, plus appears in the daily digest until resolved |
| **P3 — FYI** | Advisory, trends, completed events | **Daily email digest only** (08:00), weekly rollup for trends | Never pushes |

There is no fourth channel and no per-alert channel choice — a new alert type must be classified into exactly one row of the rules table below before it ships.

## 2. The rules table (condition → severity)

**P1 — wake me:**
- Prod-tier site hard-down > 5 min (3 consecutive failed probes, and the canary check passed — see §5)
- The Hub itself down (dead-man's switch fired — external, see §5)
- Hub database failure, or nightly backup failed/missing
- Attack playbook engaged (Under-Attack mode flipped, edge bans pushed)
- Any budget cap hit (cloud spend, partner quota-abuse trip, test-plane $10 alarm)
- Vault/KEK unlock failure at service start; any anomaly alert on mass secret access
- SSH host-key mismatch on any target (possible MITM/hijack — never auto-retried)
- Disk > 95% on any host (at 95% you're minutes from an outage; 85% is P2)
- Partner API kill-switch auto-triggered (abuse detection)
- **UPDATE 2026-08-02 (review3, per §O1):** Partner Intake unreachable > 5 min (the partner-facing platform is down)
- **UPDATE 2026-08-02 (review3, per §V9):** Uploaded cert < 7 d; auto-renewed cert < 1 d (see cert-threshold note below)
- **UPDATE 2026-08-02 (review3, per §O1):** Instance warm-up exceeded budget escalates to P1 **only if no ready instance is serving** (otherwise P2, see below)
- **UPDATE 2026-08-02 (review3, per §O1):** Partner-tier sites escalate to P1 **only on aggregate signals**: N partner sites down simultaneously, or a partner-tier target host down (a single partner-tier site hard-down is P2, see below)

**P2 — today:**
- Staging/experiment-tier site down; prod site *flapping* (collapsed to one alert, see §4)
- Error rate (5xx) above threshold; p95 latency > 2× 7-day baseline and rising
- Disk > 85%; RAM/CPU sustained > 90% without a scale event
- Drift finding the reconciler could **not** auto-repair (3 failed convergences → backoff alert), or "something is fighting the reconciler"
- Cert expiring: auto-renewed certs < 7 d (renewal is broken if this ever fires); uploaded certs < 21 d
- fail2ban mass-ban spike / auth brute-force pattern; repeated partner signature failures
- A scheduled drill failed **or did not run** (a skipped drill is a finding, not a silence)
- Hub egress degraded (canary probe failing — my monitoring is blind)
- Clock skew > 30 s on any target
- Scale-out proposal awaiting approval (propose mode) — push with the approve action link
- **UPDATE 2026-08-02 (review3, per §O1):** Feed data-stale beyond per-feed threshold (market-calendar-aware) = **P2 push** — arguably the single alert Joseph most wants from this project; **never a restart trigger** (§N3)
- **UPDATE 2026-08-02 (review3, per §O1):** Instance warm-up exceeded budget = **P2**, escalating P1 only if no ready instance is serving
- **UPDATE 2026-08-02 (review3, per §O1):** Scheduled app job failed = **P2 with consecutive-failure hysteresis**; individual run failures go to the P3 digest
- **UPDATE 2026-08-02 (review3, per §O1):** Partner-tier site hard-down = **P2 by default** (not the prod-P1 row, not the staging row), escalating to P1 only on the aggregate signals listed above
- **UPDATE 2026-08-02 (review3, per §O1):** Hub→outbox poll failing N cycles = **P2**
- **UPDATE 2026-08-02 (review3, per §O1):** Target cron job failed/stale = **P2** (interim: both delivered cron scripts curl the ntfy P2 topic on failure — two lines each — so `update-cloudflare-ufw.sh` going stale can't silently rot toward blocked users)

**P3 — digest:**
- Advice-tier findings, security-score/topology-score changes
- Drift found *and* auto-repaired (with what/when/command)
- Deploys completed (yours and partners'), scale episodes completed with cost, cert renewals succeeded
- pip-audit / dependency monthly report, Django/DRF security-release notices (jumps to P2 if the CVE matches the Hub's own surface)
- Uptime/traffic weekly trends; retention janitor and backup-restore drill summaries
- **UPDATE 2026-08-02 (review3, per §V9):** Uploaded cert < 45 d
- **UPDATE 2026-08-02 (review3, per §O1):** Individual scheduled-job run failures (P2 only on consecutive failures, above)

**UPDATE 2026-08-02 (review3, per §V9) — cert-expiry thresholds reconciled (operational layer wins):** **uploaded certs: 45 d = P3, 21 d = P2, 7 d = P1; auto-renewed certs: 7 d = P2 (renewal is broken), 1 d = P1.** This supersedes the master plan §6C thresholds; the supersession is noted inline at §6C.

## 3. Anatomy of every alert (one template, all channels)

```
[HUB P1] blog.example.tw DOWN 6 min
What:    3 consecutive probe failures (timeout) from Hub + external prober
Since:   2026-07-30 14:52 (UTC+8)
Status:  old container running; Caddy route present; DNS ok → suspect app crash
Action:  tap → site status page (rollback is one tap, no hardware key needed)
Break-glass (if Hub is unreachable): ssh atlas 'docker restart site-blog-141'
```

Rules: subject = severity + object + duration; body = what / since / current-status / **one** recommended action + deep link; **always include the break-glass command** on anything Hub-adjacent, because "Hub unreachable" is exactly when some of these fire; **always send the recovery notice** ("UP after 14 min") — an alert that never resolves teaches you to ignore alerts.

**UPDATE 2026-08-02 (review3, per §M3):** **Break-glass commands arriving over the pager channel are ADVISORY ONLY** — re-read them from the Hub-served Findings inbox (over Tailscale) before typing; **never execute a command whose only provenance is a push notification.** Push bodies are minimized: object + severity + duration + deep link; host aliases, never raw IPs; full detail lives behind the tailnet. The trade-off (self-sufficient alerts when the Hub is down) is preserved by keeping the break-glass text in the *email* copy, which the §B10 scrubber discipline and this advisory-only rule now cover.

## 4. Anti-noise rules (hard-coded, not configurable per alert)

- **Hysteresis:** open after **3** consecutive failures, close after **2** consecutive successes. Nothing alerts on a single failed probe.
- **Flap collapse:** ≥3 open/close cycles in 30 min → one "FLAPPING" alert (P2), suppress individual transitions until stable for 30 min.
- **Root-cause suppression:** host-down suppresses its sites' site-down alerts; zone-down (all targets in a zone unreachable) suppresses its hosts' — you get **one** alert naming the root, with the suppressed list inside it.
- **Ack semantics:** acking (tap in ntfy / click in email / Findings inbox) stops repeats but keeps the finding open in the inbox until actually resolved. Ack ≠ resolve.
- **Storm breaker:** >10 pushes in 10 minutes → collapse into one "ALERT STORM (n alerts)" P1 and switch to 10-min summaries until the rate drops. A pager that machine-guns is a pager turned off.
- **No quiet hours for P1. Ever.** P2/P3 respect the phone's own night mode (that's why P2 uses normal priority — the OS handles it).

## 5. Who watches the watcher (the part most setups miss)

The Hub can't report its own death, so three externals stand behind it:

1. **Dead-man's switch** — healthchecks.io (free): the Hub's probe cycle pings after each *completed* run (proving scheduler + broker + worker + SSH end-to-end, not just that cron ticks). Missed pings > 10 min → healthchecks emails **and** triggers ntfy (it can call a webhook = ntfy publish URL).
2. **External uptime probe** — an independent free monitor (e.g. UptimeRobot) watches 2–3 prod domains from outside your networks entirely. Catches "my whole ISP/zone is down and so is my monitoring."
3. **Canary rule** — before the Hub declares a mass outage, it probes a known-good external endpoint; if the canary also fails, the alert becomes "Hub egress degraded" (P2, one alert) instead of N false site-down pages.

Interim (before the Hub exists): `server-watch.sh` (shipped alongside this doc) runs from cron on each server and implements the same protocol — thresholds, hysteresis-by-state-file, recovery notices, heartbeat ping — pushing over ntfy.

**UPDATE 2026-08-02 (review3, per §V8):** `server-watch.sh`'s status is resolved — it **IS delivered** (with the per-server publish tokens per §6 below): it joins the `server-hardening.md` script table and review3 §Q8 custody (shellcheck + shfmt + `bash -n` static gates, T2 idempotency testing in the `hub-test-target` container, canonical home in the repo under `scripts/`). The **monthly pager test (§7) joins build-process §3's scheduled-drills list**, so a skipped pager drill alerts like a down site (per §2's "a skipped drill is a finding, not a silence").

## 6. Channel setup (10 minutes, one time)

**ntfy (primary pager):** install the ntfy app (iOS/Android) → subscribe to two topics with unguessable names, e.g. `hub-p1-<random>` (in-app: exempt from Do-Not-Disturb, custom sound) and `hub-p2-<random>`. Publishing is one HTTP call — no account needed on ntfy.sh, or self-host later (but never on the Hub itself: the pager must not die with the patient). Treat topic names as secrets.

**UPDATE 2026-08-02 (review3, per §M3):** ntfy access tokens are **MANDATORY from day one** — not "defense-in-depth": reserved/protected topics, deny-all default, and a **distinct publish token per server** (and for healthchecks) so one compromised host is identifiable and revocable. Topic names are vaulted secrets. The threat model (§6.8) gains an **"alerting channel" row** recording the spoof/flood/leak attacker on the alerting channel: any host holding the bare topic name could otherwise **read** every alert (hostnames, container names, live incident state, via a third-party service), **spoof** alerts including a forged P1 break-glass command, or **flood** the topic until the §4 storm breaker collapses a real alert into an attacker-generated summary.

```bash
# P1 (max priority, tagged, repeats handled by sender):
curl -s -H "Priority: max" -H "Tags: rotating_light" \
     -H "Title: [HUB P1] blog.example.tw DOWN 6 min" \
     -d "$(cat alert-body.txt)" https://ntfy.sh/hub-p1-XXXXXXXX
```

**Email (digest + copy-of-P1):** any SMTP (or the Hub's provider adapter later). Digest at 08:00 local; P1 copies immediately (email is the paper trail, never the pager).

**Fallback decision, recorded:** if ntfy proves unreliable for you in practice, the drop-in replacement is Pushover (one-time US$5, same one-call HTTP publish). Protocol unchanged.

## 7. Standing hygiene

- **Weekly 5-minute review** (a P3 digest section prompts it): every P1/P2 of the week — was each *actionable*? Anything you ignored twice gets reclassified down or its threshold moved. Alert fatigue is a bug with a severity, and it's P1.
- **Monthly pager test:** a scheduled synthetic P1 ("TEST — ack me") verifies the whole path phone-deep; failing to receive it is itself a P1 (via the email copy). **UPDATE 2026-08-02 (review3, per §V8):** this test joins build-process §3's scheduled-drills list — a skipped pager drill alerts like a down site.
- **Every alert is also a Finding** (§F2 model) with the same fingerprint — the inbox is the queryable history; the pager is only the interrupt.
