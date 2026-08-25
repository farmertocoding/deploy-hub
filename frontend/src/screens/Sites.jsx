// Sites (§F1): every site the Hub knows, flattened from the projects payload (the
// one list endpoint that exists this side of Task 4), each with its manifest
// currency, its TLS state and — on the detail — the T3 recovery actions (§F5).
//
// The site detail (SiteStatus) is one of §F6's three phone-width screens: single
// column, no fixed widths, the T3 actions reachable under a thumb. The
// unproxied-cert refusal renders as a VISIBLE site state with its Finding link
// (Task 3's model): the payload field it reads, `site.cert_refusal =
// {detail, finding_id}`, arrives with Task 4's regeneration — until then no site
// carries it and the state renders for none, which is the truth.
import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { ActionButton } from "../Tiers.jsx";
import { ACTION_TIERS, tierFor } from "../actions.js";
import { EmptyState, ErrorLine, LoadingLine, routeHash } from "../Chrome.jsx";
import { safeText } from "../safe-display.js";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

export function t3SiteActions() {
  return ACTION_TIERS.filter((row) => row.tier === "T3").map((row) => row.id);
}

export async function rollbackSite(siteId) {
  return api(`v1/sites/${siteId}/rollback/`, {});
}

export async function createPreview(siteId, ref, confirmName) {
  return api(`v1/sites/${siteId}/preview/`, { ref, confirm_name: confirmName });
}

export async function takedownPartnerSite(siteId, confirmName) {
  return api(`v1/sites/${siteId}/takedown/`, { confirm_name: confirmName });
}

export function adoptActions() {
  return ["site.adopt.start", "site.adopt.cancel"];
}

export function adoptDiff(site, actionId) {
  const domain = site.domain || site.name;
  const zone = site.dns_zone || "";
  const temp = site.adopt?.temp_name
    || (zone ? `${site.name}-adopt-….${zone}` : `${site.name}-adopt-…`);
  const volumes = (site.adopt?.volumes || []).join(", ") || "registered volumes";
  if (actionId === "site.adopt.start") {
    return `Flip ${domain} after verify; decommission the old path; ${volumes} stay registered.`;
  }
  if (actionId === "site.adopt.cancel") {
    return `Abandon ${temp}; delete temp DNS; leave ${domain} serving.`;
  }
  throw new Error(`not an adopt action: ${actionId}`);
}

// HTTP start slipped 2026-08-23: MUST start is adopt_flow. This POST is the
// Sites wiring so ?sim=plan can confirm the T2 diff; live 404s until a later
// view owns the route. live_compose_path is sent only when the operator typed it.
export async function startAdopt(siteId, opts = {}) {
  const body = {};
  if (opts.live_compose_path) body.live_compose_path = opts.live_compose_path;
  return api(`v1/sites/${siteId}/adopt/`, body);
}

export async function cancelAdopt(siteId) {
  return api(`v1/sites/${siteId}/adopt/`, { cancel: true });
}

export function flattenSites(projects) {
  return (projects || []).flatMap((p) =>
    (p.sites || []).map((s) => ({ ...s, project: p.name })));
}

export function isPartnerSite(site) {
  return Boolean(site?.partner || site?.partner_site);
}

export function PartnerBadge({ site }) {
  if (!isPartnerSite(site)) return null;
  return <span aria-label="partner site">◆ partner</span>;
}

export function jobCreateVisible(site) {
  return !isPartnerSite(site) && Boolean(site?.job_create);
}

const SITE_FILTERS = [
  { id: "all", label: "All" },
  { id: "mine", label: "Mine" },
  { id: "partner", label: "Partner" },
];

export function ManifestLine({ site }) {
  if (site.latest_manifest_version == null)
    return <span style={{ color: "#8b949e" }}>no manifest yet</span>;
  return site.manifest_current
    ? <span style={{ color: "#3fb950" }}>✓ manifest v{site.latest_manifest_version} matches current scan</span>
    : <span style={{ color: "#e3b341" }}>⚠ manifest v{site.latest_manifest_version} predates current scan</span>;
}

// The unproxied-cert refusal as a SITE STATE, not a buried log line: the pipeline
// refused this site a certificate and said why, and the Finding carries the full
// story — the link routes to the finding detail, never through the map (§F6).
// Observed-state badges the §F8 seed paints: warming (elapsed/expected),
// data-stale, single-instance-only (scale_ready === false), single-instance
// (F8 one-copy), cert-expiring. Symbol + words, never colour. Omitted
// scale_ready does not paint — not `if (!site.scale_ready)`.
export function SiteObserved({ site }) {
  if (!site) return null;
  const bits = [];
  if (site.observed === "warming" || site.warming) {
    const elapsed = site.elapsed_s ?? site.elapsed;
    const expected = site.expected_s ?? site.expected;
    bits.push(`warming ${elapsed}s elapsed / ${expected}s expected`);
  }
  if (site.badge === "data-stale" || site.data_stale || site.observed === "data-stale")
    bits.push("data-stale");
  if (site.scale_ready === false) bits.push("single-instance-only");
  if (site.single_instance || site.instances === 1) bits.push("single-instance");
  if (site.cert_expiring) bits.push("cert expiring");
  if (!bits.length) return null;
  return <span>{bits.join(" · ")}</span>;
}

export function CertState({ site }) {
  if (!site.cert_refusal) return null;
  return (
    <p style={{ color: "#ff7b72", margin: "4px 0" }}>
      ⛔ TLS refused: {safeText(site.cert_refusal.detail)}{" "}
      <a href={routeHash("findings", site.cert_refusal.finding_id)}
        style={{ color: "#79c0ff" }}>View finding</a>
    </p>
  );
}

// Attack playbook as a SITE STATE, CertState twin (D-057 / C3): Under-Attack
// is visible, and a missing edge ref is a degraded notify-only line, never
// silent. Task 7 must not rewrite this component.
export function AttackState({ site }) {
  if (!site.attack_state) return null;
  const degraded = site.attack_state.mode === "notify_only";
  const label = degraded
    ? `⚠ Attack playbook notify-only: ${safeText(site.attack_state.detail)}`
    : `⛔ Under attack: ${safeText(site.attack_state.detail)}`;
  return (
    <p style={{ color: degraded ? "#e3b341" : "#ff7b72", margin: "4px 0" }}>
      {label}{" "}
      <a href={routeHash("findings", site.attack_state.finding_id)}
        style={{ color: "#79c0ff" }}>View finding</a>
    </p>
  );
}

// Sites-detail backup list (C7 / D-063 / D-122): metadata + restore <pre>,
// T2 test-now, T1 Restore into clean container. Command block stays.
export async function testBackupNow(siteId, unitId) {
  return api(`v1/sites/${siteId}/backups/${unitId}/test/`, {});
}

export async function restoreBackup(siteId, unitId, { checkrun_pk, confirm_name }) {
  return api(`v1/sites/${siteId}/backups/${unitId}/restore/`, {
    checkrun_pk, confirm_name,
  });
}

export function BackupPanel({ site, backups, onTestNow = () => {}, onRestore }) {
  const [confirming, setConfirming] = useState(false);
  if (!backups) return null;
  const units = backups.units || [];
  const dumps = units.flatMap((u) =>
    (u.dumps || []).map((d) => ({ ...d, kind: u.kind, unit_id: u.id })));
  const restore = onRestore || (async (current, unit, dump, name) => {
    if (!unit || !dump) return;
    await restoreBackup(current.id, unit.id, {
      checkrun_pk: dump.id, confirm_name: name,
    });
  });
  return (
    <div style={{ ...box, borderColor: "#3fb950" }}>
      <h4 style={{ margin: "0 0 8px" }}>Backups</h4>
      {dumps.length === 0
        ? <div style={{ color: "#8b949e" }}>No dumps yet</div>
        : dumps.map((d) => (
          <div key={d.id}>
            {d.kind} · {d.bytes} bytes · {safeText(String(d.digest || "").slice(0, 12))}
            {d.stored_at ? ` · ${safeText(d.stored_at)}` : ""}
          </div>
        ))}
      {backups.restore_command
        ? <pre style={{ ...box, overflow: "auto", whiteSpace: "pre-wrap" }}>
            {safeText(backups.restore_command)}
          </pre>
        : null}
      {units.length > 0 && (confirming ? (
        <div role="dialog" aria-label="Test backup now">
          <p>Seal a dump with this site's backup key, never the KEK.</p>
          <button style={{ ...box, marginRight: 8 }}
            onClick={() => { onTestNow(site, units[0]); setConfirming(false); }}>
            Confirm — Test backup now</button>
          <button style={box} onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      ) : (
        <button style={box} onClick={() => setConfirming(true)}>
          Test backup now</button>
      ))}
      {dumps.length > 0 && (
        <ActionButton row={tierFor("site.backup_restore")}
          confirmName={site.name}
          onRun={({ name }) => restore(site, units[0], dumps[0], name)} />
      )}
    </div>
  );
}

// Adopt plan on the site detail: edge_owner is a Site column (D-052), shown
// here and never prompted per run. Start/cancel are T2 because the start
// confirm names the flip + decommission. No /srv/sites walk — the path field
// is the explicit live_compose_path argument, blank meaning unset.
export function AdoptPlan({
  site, liveComposePath, onLiveComposePath, onRun = () => {}, onUndo = () => {},
}) {
  const [path, setPath] = useState(liveComposePath ?? "");
  const value = liveComposePath !== undefined ? liveComposePath : path;
  const setValue = onLiveComposePath || setPath;
  const stage = site.adopt?.stage;
  const classified = site.adopt?.classified || {};
  const volumes = site.adopt?.volumes || [];
  const showStart = !stage || stage === "plan" || stage === "abandoned";
  const showCancel = stage === "verify" || stage === "temp_dns";
  const roles = Object.entries(classified).filter(([, name]) => name);
  return (
    <div style={{ ...box, borderColor: "#3fb950" }}>
      <h4 style={{ margin: "0 0 8px" }}>Adopt plan</h4>
      <div>edge owner: {site.edge_owner || "host_caddy"}</div>
      {stage && <div>stage: {stage}</div>}
      {site.adopt?.temp_name ? <div>temp: {site.adopt.temp_name}</div> : null}
      {roles.map(([role, name]) => (
        <div key={role}>{role}: {name}</div>
      ))}
      {volumes.length > 0 && <div>volumes: {volumes.join(", ")}</div>}
      {site.origin_ca_planted === false && (
        <div>Origin-CA unplanted — plant before a proxied public deploy.</div>
      )}
      <label style={{ display: "grid", gap: 4, marginTop: 8 }}>
        live_compose_path
        <input name="live_compose_path" style={box} value={value}
          placeholder="explicit path; blank skips the drift check"
          onChange={(e) => setValue(e.target.value)} />
      </label>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
        {showStart && (
          <ActionButton row={tierFor("site.adopt.start")}
            summary={adoptDiff(site, "site.adopt.start")}
            onRun={() => onRun("site.adopt.start", site)}
            onUndo={() => onUndo("site.adopt.start", site)} />
        )}
        {showCancel && (
          <ActionButton row={tierFor("site.adopt.cancel")}
            summary={adoptDiff(site, "site.adopt.cancel")}
            onRun={() => onRun("site.adopt.cancel", site)}
            onUndo={() => onUndo("site.adopt.cancel", site)} />
        )}
      </div>
    </div>
  );
}

// §F6 phone screen: site status + its T3 actions. Live Sites passes the T3
// ids; only site.rollback has HTTP (pipeline.rollback). Restart / re-run
// render so the table is visible; they do not invent engines.
export function SiteStatus({
  site, actions = [], onRun = () => {}, onUndo = () => {},
  backups: backupsProp, onTestNow,
}) {
  const [liveComposePath, setLiveComposePath] = useState("");
  const [previewRef, setPreviewRef] = useState("");
  const [backups, setBackups] = useState(backupsProp);
  useEffect(() => {
    if (backupsProp !== undefined) {
      setBackups(backupsProp);
      return;
    }
    if (site?.id == null) return;
    api(`v1/sites/${site.id}/backups/`).then(({ status, data }) => {
      if (status === 200) setBackups(data);
    });
  }, [site?.id, backupsProp]);
  const testNow = onTestNow || (async (_current, unit) => {
    if (!unit) return;
    const { status } = await testBackupNow(site.id, unit.id);
    if (status === 201) {
      const refreshed = await api(`v1/sites/${site.id}/backups/`);
      if (refreshed.status === 200) setBackups(refreshed.data);
    }
  });
  const run = (id, current) => {
    if (id === "site.adopt.start") {
      return onRun(id, {
        ...current,
        adopt: {
          ...current.adopt,
          live_compose_path: liveComposePath || current.adopt?.live_compose_path || undefined,
        },
      });
    }
    return onRun(id, current);
  };
  return (
    <div style={{ ...box, marginTop: 8, maxWidth: "100%",
      display: "grid", gap: 8 }}>
      <h3 style={{ margin: 0 }}>{site.name}{site.domain ? ` — ${site.domain}` : ""}</h3>
      <div style={{ color: "#8b949e" }}>project: {site.project}</div>
      <div><ManifestLine site={site} /></div>
      <div><SiteObserved site={site} /></div>
      <div><PartnerBadge site={site} /></div>
      <CertState site={site} />
      <AttackState site={site} />
      <BackupPanel site={site} backups={backups} onTestNow={testNow} />
      <label style={{ display: "grid", gap: 4 }}>
        preview ref
        <input aria-label="preview ref" style={box} value={previewRef}
          onChange={(e) => setPreviewRef(e.target.value)} />
      </label>
      <ActionButton row={tierFor("site.preview_create")}
        confirmName={site.name}
        summary={`Create preview of ${site.name} at ${previewRef}`}
        onRun={() => createPreview(site.id, previewRef, site.name)} />
      {!isPartnerSite(site) && (site.edge_owner || site.adopt) && (
        <AdoptPlan site={site} liveComposePath={liveComposePath}
          onLiveComposePath={setLiveComposePath} onRun={run} onUndo={onUndo} />
      )}
      {jobCreateVisible(site) && (
        <button style={box}>Create job</button>
      )}
      {isPartnerSite(site) && (
        <>
          <div>{site.domain || site.name} route → 410</div>
          <ActionButton row={tierFor("partner.site_takedown")}
            confirmName={site.domain || site.name}
            summary={`${site.domain || site.name} route → 410`}
            onRun={() => onRun("partner.site_takedown", site)} />
        </>
      )}
      {actions.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {actions.map((id) => (
            <ActionButton key={id} row={tierFor(id)}
              onRun={() => onRun(id, site)} onUndo={() => onUndo(id, site)} />
          ))}
        </div>
      )}
    </div>
  );
}

export function SitesView({
  phase, sites, selectedId, onSelect, onError, onNav, filter: filterProp,
}) {
  const [filter, setFilter] = useState(filterProp || "all");
  if (phase === "loading") return <LoadingLine what="sites" />;
  if (phase === "error") return <ErrorLine text={onError.text} onRetry={onError.retry} />;
  if (!sites.length)
    return <EmptyState
      sentence="No sites yet — configure one from a scanned project on Home."
      button="Open Home" onAction={() => onNav("home")} />;
  const visible = sites.filter((s) => {
    if (filter === "partner") return isPartnerSite(s);
    if (filter === "mine") return !isPartnerSite(s);
    return true;
  });
  const selected = visible.find((s) => String(s.id) === String(selectedId))
    || sites.find((s) => String(s.id) === String(selectedId));
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
        {SITE_FILTERS.map((row) => (
          <button key={row.id} style={{ ...box, opacity: filter === row.id ? 1 : 0.6 }}
            onClick={() => setFilter(row.id)}>{row.label}</button>
        ))}
      </div>
      {visible.map((s) => (
        <div key={s.id} style={{ ...box, marginBottom: 8, cursor: "pointer" }}
          role="button" tabIndex={0} onClick={() => onSelect(s.id)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(s.id); } }}>
          <strong>{s.name}</strong>{s.domain ? ` — ${s.domain}` : ""}{" "}
          <span style={{ color: "#8b949e" }}>({s.project})</span>{" "}
          <PartnerBadge site={s} />{" "}
          <ManifestLine site={s} />{" "}
          <SiteObserved site={s} />
          <CertState site={s} />
          <AttackState site={s} />
        </div>
      ))}
      {selected && (
        <SiteStatus site={selected} actions={t3SiteActions()}
          onRun={(id, site) => {
            if (id === "site.rollback") return rollbackSite(site.id);
            if (id === "partner.site_takedown") {
              return takedownPartnerSite(site.id, site.domain || site.name);
            }
            if (id === "site.adopt.start") {
              return startAdopt(site.id, {
                live_compose_path: site.adopt?.live_compose_path,
              });
            }
            if (id === "site.adopt.cancel") return cancelAdopt(site.id);
          }} />
      )}
    </div>
  );
}

export default function Sites({ route, onNav }) {
  const [projects, setProjects] = useState(undefined);
  const [partnerSiteIds, setPartnerSiteIds] = useState(() => new Set());
  const [error, setError] = useState("");
  const load = () => {
    setError("");
    setProjects(undefined);
    api("v1/projects/").then(({ status, data }) => {
      if (status === 200) setProjects(data);
      else setError(data.detail || `Could not load sites (HTTP ${status})`);
    });
    api("v1/partners/").then(({ status, data }) => {
      if (status !== 200) return;
      const ids = new Set();
      for (const partner of data.partners || []) {
        for (const id of partner.site_ids || []) ids.add(id);
      }
      setPartnerSiteIds(ids);
    });
  };
  useEffect(load, []);
  const phase = error ? "error" : projects === undefined ? "loading" : "live";
  const sites = flattenSites(projects).map((s) => ({
    ...s, partner: Boolean(s.partner || partnerSiteIds.has(s.id)),
  }));
  return <SitesView phase={phase} sites={sites}
    selectedId={route.id} onSelect={(id) => onNav("sites", id)}
    onError={{ text: error, retry: load }} onNav={onNav} />;
}
