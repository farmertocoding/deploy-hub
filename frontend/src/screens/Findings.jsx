// Findings (§F1/§F2): the inbox is Task 13's (it needs the Finding model); this
// screen is its frame — the designed empty state, and the FindingDetail contract the
// Sites cert-refusal link and every alert deep link land on. FindingDetail is one of
// §F6's three phone-width screens: an alert at 2 a.m. opens THIS, never the map.
import React from "react";
import { EmptyState, ErrorLine, LoadingLine } from "../Chrome.jsx";
import { safeText } from "../safe-display.js";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

// finding = { id, title, severity, site, detail, fix_hint } — Task 13's serializer
// shape. Server prose can quote repo/site content, so it takes the display sanitizer
// like every repo-controlled string on the readiness screen (dom-bidi-display).
export function FindingDetail({ finding, onBack }) {
  return (
    <div style={{ ...box, marginTop: 8, maxWidth: "100%", display: "grid", gap: 8 }}>
      <h3 style={{ margin: 0 }}>{safeText(finding.title)}</h3>
      <div style={{ color: "#8b949e" }}>
        {finding.severity}{finding.site ? ` · ${finding.site}` : ""}</div>
      <p style={{ margin: 0, whiteSpace: "pre-line", overflowWrap: "anywhere" }}>
        {safeText(finding.detail)}</p>
      {finding.fix_hint && (
        <p style={{ margin: 0, color: "#8b949e", whiteSpace: "pre-line",
          overflowWrap: "anywhere" }}>Fix: {safeText(finding.fix_hint)}</p>
      )}
      <div><button style={box} onClick={onBack}>Back to findings</button></div>
    </div>
  );
}

export function FindingsView({ phase, findings = [], onError, onNav }) {
  if (phase === "loading") return <LoadingLine what="findings" />;
  if (phase === "error") return <ErrorLine text={onError.text} onRetry={onError.retry} />;
  if (!findings.length)
    return <EmptyState
      sentence="No findings yet — scans and monitors file what they refuse or notice here."
      button="Open Home and scan a project" onAction={() => onNav("home")} />;
  return <div style={{ padding: 16 }}>{findings.map((f) => (
    <div key={f.id} style={{ ...box, marginBottom: 8 }}>{safeText(f.title)}</div>
  ))}</div>;
}

export default function Findings({ route, onNav }) {
  // The inbox fetch lands with Task 13's Finding model; the frame is honest about
  // holding nothing until then — including for a deep link to a finding it cannot
  // fetch yet, which must say so rather than render a blank detail.
  if (route?.id)
    return (
      <div style={{ padding: 16 }}>
        <p style={{ color: "#8b949e" }}>Finding {route.id} — the findings inbox lands
          with the Finding model (Task 13); nothing to show yet.</p>
        <button style={box} onClick={() => onNav("findings")}>Back to findings</button>
      </div>
    );
  return <FindingsView phase="live" findings={[]} onNav={onNav} />;
}
