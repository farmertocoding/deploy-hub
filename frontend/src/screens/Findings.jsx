// Findings inbox (§F2): one attention queue over /api/v1/findings/. Filters are
// the contract (state / severity / entity). Severity chips carry an icon AND a
// label. Accept-risk will not POST without a reason (grey chip shows why). Ack
// does not drop the row. FindingDetail stays a §F6 phone-width screen and
// renders the §6.6 what / why / exact-fix fields (API: title / body / fix_action;
// the 12a frame still accepts detail / fix_hint / site).
import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { EmptyState, ErrorLine, LoadingLine, routeHash } from "../Chrome.jsx";
import { safeText } from "../safe-display.js";
import { box } from "../ui/surface.js";

function filterFromSearch() {
  try {
    const entity = new URLSearchParams(window.location.search || "").get("entity");
    return entity ? { entity } : {};
  } catch {
    return {};
  }
}

const SEVERITY = {
  p1: { icon: "⛔", label: "P1" },
  p2: { icon: "⚠", label: "P2" },
  p3: { icon: "ℹ", label: "P3" },
};

export function reasonIsValid(reason) {
  return Boolean((reason || "").trim());
}

export async function acceptRisk(id, reason) {
  if (!reasonIsValid(reason)) {
    return {
      status: 400,
      data: { errors: { reason: [{
        code: "required",
        message: "Accept-risk requires a one-line reason (§F2).",
      }] } },
    };
  }
  return api(`v1/findings/${id}/transition/`, {
    action: "accept_risk", reason: (reason || "").trim(),
  });
}

export async function ackFinding(id) {
  return api(`v1/findings/${id}/transition/`, { action: "ack" });
}

export function SeverityChip({ severity }) {
  const row = SEVERITY[severity] || { icon: "●", label: String(severity || "").toUpperCase() };
  return (
    <span aria-label={`severity ${row.label}`}
      style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      {row.icon} {row.label}
    </span>
  );
}

export function StateChip({ finding }) {
  if (finding.state === "accepted") {
    return (
      <span style={{ background: "var(--hud-muted)", color: "#e6e6e6",
        padding: "2px 8px", borderRadius: 12 }}>
        accepted — {safeText(finding.accepted_reason)}
      </span>
    );
  }
  return <span>{finding.state}</span>;
}

export function AcceptRiskForm({ finding, onAccept }) {
  const [reason, setReason] = useState("");
  const ok = reasonIsValid(reason);
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
      <input aria-label="Accept-risk reason" value={reason} style={box}
        placeholder="one-line reason"
        onChange={(e) => setReason(e.target.value)} />
      <button style={box} disabled={!ok}
        onClick={() => ok && onAccept?.(finding.id, reason)}>
        Accept risk
      </button>
    </div>
  );
}

export function FindingDetail({ finding, onBack, onAck, onAccept }) {
  const site = finding.site || finding.entity || "";
  const why = finding.detail || finding.body || "";
  const fix = finding.fix_hint || finding.fix_action || "";
  const canAck = finding.state === "open";
  const canAccept = finding.state === "open" || finding.state === "acked";
  return (
    <div style={{ ...box, marginTop: 8, maxWidth: "100%", display: "grid", gap: 8 }}>
      <h3 style={{ margin: 0 }}>{safeText(finding.title)}</h3>
      <div style={{ color: "var(--hud-muted)" }}>
        <SeverityChip severity={finding.severity} />
        {site ? ` · ${site}` : ""}
        {finding.state ? <>{" · "}<StateChip finding={finding} /></> : null}
      </div>
      <p style={{ margin: 0, whiteSpace: "pre-line", overflowWrap: "anywhere" }}>
        {safeText(why)}</p>
      {fix && (
        <p style={{ margin: 0, color: "var(--hud-muted)", whiteSpace: "pre-line",
          overflowWrap: "anywhere" }}>Fix: {safeText(fix)}</p>
      )}
      {canAck && (
        <div>
          <button style={box} onClick={() => onAck?.(finding.id)}>Ack</button>
        </div>
      )}
      {canAccept && <AcceptRiskForm finding={finding} onAccept={onAccept} />}
      <div><button style={box} onClick={onBack}>Back to findings</button></div>
    </div>
  );
}

export function FindingsView({
  phase, findings = [], filter = {}, onFilter, onError, onNav, onAck, onAccept,
}) {
  if (phase === "loading") return <LoadingLine what="findings" />;
  if (phase === "error") return <ErrorLine text={onError.text} onRetry={onError.retry} />;
  if (!findings.length)
    return <EmptyState
      sentence="No findings yet — scans and monitors file what they refuse or notice here."
      button="Open Home and scan a project" onAction={() => onNav("home")} />;
  const rows = findings.filter((f) => {
    if (filter.state && f.state !== filter.state) return false;
    if (filter.severity && f.severity !== filter.severity) return false;
    if (filter.entity && f.entity !== filter.entity) return false;
    return true;
  });
  const entities = [...new Set(findings.map((f) => f.entity).filter(Boolean))].sort();
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
        <label>severity{" "}
          <select aria-label="Filter by severity" value={filter.severity || ""}
            onChange={(e) => onFilter?.({ ...filter, severity: e.target.value || undefined })}>
            <option value="">all</option>
            <option value="p1">p1</option>
            <option value="p2">p2</option>
            <option value="p3">p3</option>
          </select>
        </label>
        <label>state{" "}
          <select aria-label="Filter by state" value={filter.state || ""}
            onChange={(e) => onFilter?.({ ...filter, state: e.target.value || undefined })}>
            <option value="">all</option>
            <option value="open">open</option>
            <option value="acked">acked</option>
            <option value="accepted">accepted</option>
            <option value="resolved">resolved</option>
          </select>
        </label>
        <label>entity{" "}
          <select aria-label="Filter by entity" value={filter.entity || ""}
            onChange={(e) => onFilter?.({ ...filter, entity: e.target.value || undefined })}>
            <option value="">all</option>
            {entities.map((entity) => (
              <option key={entity} value={entity}>{entity}</option>
            ))}
          </select>
        </label>
      </div>
      {rows.map((f) => (
        <div key={f.id} style={{ ...box, marginBottom: 8 }}>
          <SeverityChip severity={f.severity} />{" "}
          <StateChip finding={f} />{" "}
          <a href={routeHash("findings", f.id)}
            onClick={(e) => { e.preventDefault(); onNav?.("findings", f.id); }}>
            <strong>{safeText(f.title)}</strong>
          </a>
          {(f.state === "open") && (
            <div style={{ marginTop: 8 }}>
              <button style={box} onClick={() => onAck?.(f.id)}>Ack</button>
            </div>
          )}
          {(f.state === "open" || f.state === "acked") && (
            <AcceptRiskForm finding={f} onAccept={onAccept} />
          )}
        </div>
      ))}
    </div>
  );
}

export async function findingsSnapshot() {
  const { status, data } = await api("v1/findings/");
  if (status !== 200 || !Array.isArray(data?.data)) throw { status };
  return data;
}

export function attachFindings(events, onRows) {
  const handler = (event) => {
    if (event.__snapshot) {
      onRows(event.data);
      return;
    }
    if (event.__snapshot_failed) return;
    findingsSnapshot().then((snap) => onRows(snap.data)).catch(() => {});
  };
  events.subscribe("findings", handler, findingsSnapshot);
  return () => events.unsubscribe("findings");
}

export default function Findings({ route, onNav, events }) {
  const [bundle, setBundle] = useState(undefined);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState(filterFromSearch);
  const load = () => {
    setError("");
    setBundle(undefined);
    const path = route?.id ? `v1/findings/${route.id}/` : "v1/findings/";
    api(path).then(({ status, data }) => {
      if (status === 200) setBundle(data);
      else setError(data.detail || `Could not load findings (HTTP ${status})`);
    });
  };
  const subscribe = events?.subscribe;
  const unsubscribe = events?.unsubscribe;
  useEffect(load, [route?.id]);
  useEffect(() => {
    if (!subscribe || route?.id) return undefined;
    return attachFindings({ subscribe, unsubscribe }, (rows) => {
      setError("");
      setBundle({ data: rows });
    });
  }, [subscribe, unsubscribe, route?.id]);

  const phase = error ? "error" : bundle === undefined ? "loading" : "live";
  const onError = { text: error, retry: load };
  if (route?.id) {
    if (phase === "loading") return <LoadingLine what="finding" />;
    if (phase === "error") return <ErrorLine text={onError.text} onRetry={onError.retry} />;
    if (bundle?.data)
      return <FindingDetail finding={bundle.data} onBack={() => onNav("findings")}
        onAck={(id) => ackFinding(id).then(load)}
        onAccept={(id, reason) => acceptRisk(id, reason).then(load)} />;
    return (
      <div style={{ padding: 16 }}>
        <p style={{ color: "var(--hud-muted)" }}>Finding {route.id} was not found.</p>
        <button style={box} onClick={() => onNav("findings")}>Back to findings</button>
      </div>
    );
  }
  return <FindingsView phase={phase} findings={bundle?.data || []} filter={filter}
    onFilter={setFilter} onError={onError} onNav={onNav}
    onAck={(id) => ackFinding(id).then(load)}
    onAccept={(id, reason) => acceptRisk(id, reason).then(load)} />;
}
