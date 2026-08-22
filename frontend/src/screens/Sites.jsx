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
import { tierFor } from "../actions.js";
import { EmptyState, ErrorLine, LoadingLine, routeHash } from "../Chrome.jsx";
import { safeText } from "../safe-display.js";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

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

// §F6 phone screen: site status + its T3 actions. `actions` is the list of action
// ids the server says are available for THIS site — Task 13 supplies it from the
// generated payload; today no site action endpoints exist, so callers pass [] and
// the row renders nothing rather than buttons that would 404.
export function SiteStatus({ site, actions = [], onRun = () => {}, onUndo = () => {} }) {
  return (
    <div style={{ ...box, marginTop: 8, maxWidth: "100%",
      display: "grid", gap: 8 }}>
      <h3 style={{ margin: 0 }}>{site.name}{site.domain ? ` — ${site.domain}` : ""}</h3>
      <div style={{ color: "#8b949e" }}>project: {site.project}</div>
      <div><ManifestLine site={site} /></div>
      <CertState site={site} />
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
      {selected && <SiteStatus site={selected} />}
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
