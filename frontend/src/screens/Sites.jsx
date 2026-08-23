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
// data-stale, single-instance, cert-expiring. Symbol + words, never colour.
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
export function SiteStatus({ site, actions = [], onRun = () => {}, onUndo = () => {} }) {
  const [liveComposePath, setLiveComposePath] = useState("");
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
      <CertState site={site} />
      {(site.edge_owner || site.adopt) && (
        <AdoptPlan site={site} liveComposePath={liveComposePath}
          onLiveComposePath={setLiveComposePath} onRun={run} onUndo={onUndo} />
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

export function SitesView({ phase, sites, selectedId, onSelect, onError, onNav }) {
  if (phase === "loading") return <LoadingLine what="sites" />;
  if (phase === "error") return <ErrorLine text={onError.text} onRetry={onError.retry} />;
  if (!sites.length)
    return <EmptyState
      sentence="No sites yet — configure one from a scanned project on Home."
      button="Open Home" onAction={() => onNav("home")} />;
  const selected = sites.find((s) => String(s.id) === String(selectedId));
  return (
    <div style={{ padding: 16 }}>
      {sites.map((s) => (
        <div key={s.id} style={{ ...box, marginBottom: 8, cursor: "pointer" }}
          role="button" tabIndex={0} onClick={() => onSelect(s.id)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(s.id); } }}>
          <strong>{s.name}</strong>{s.domain ? ` — ${s.domain}` : ""}{" "}
          <span style={{ color: "#8b949e" }}>({s.project})</span>{" "}
          <ManifestLine site={s} />
          <CertState site={s} />
        </div>
      ))}
      {selected && (
        <SiteStatus site={selected} actions={t3SiteActions()}
          onRun={(id, site) => {
            if (id === "site.rollback") return rollbackSite(site.id);
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
  const [error, setError] = useState("");
  const load = () => {
    setError("");
    setProjects(undefined);
    api("v1/projects/").then(({ status, data }) => {
      if (status === 200) setProjects(data);
      else setError(data.detail || `Could not load sites (HTTP ${status})`);
    });
  };
  useEffect(load, []);
  const phase = error ? "error" : projects === undefined ? "loading" : "live";
  return <SitesView phase={phase} sites={flattenSites(projects)}
    selectedId={route.id} onSelect={(id) => onNav("sites", id)}
    onError={{ text: error, retry: load }} onNav={onNav} />;
}
