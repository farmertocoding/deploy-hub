// Targets (§F1): the machines the Hub deploys to. There is no targets list endpoint
// yet (it lands with Task 4's regeneration), so the live state IS the designed empty
// state — one sentence and the single action that populates the screen, which today
// is the provision CLI. The view takes its phase by prop so all states are
// renderable (and pinned) before the endpoint exists.
import React, { useState } from "react";
import { EmptyState, ErrorLine, LoadingLine } from "../Chrome.jsx";

const PROVISION_CMD = "python -m hub provision <host>";

export function TargetsView({ phase, targets = [], onError, onCopy }) {
  if (phase === "loading") return <LoadingLine what="targets" />;
  if (phase === "error") return <ErrorLine text={onError.text} onRetry={onError.retry} />;
  if (!targets.length)
    return <EmptyState
      sentence="No targets enrolled — provision a machine and it appears here."
      button="Copy the provision command" onAction={onCopy} />;
  return (
    <div style={{ padding: 16 }}>
      {targets.map((t) => <div key={t.id}>{t.name}</div>)}
    </div>
  );
}

export default function Targets() {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <TargetsView phase="live" targets={[]}
        onCopy={() => navigator.clipboard.writeText(PROVISION_CMD)
          .then(() => setCopied("ok"), () => setCopied("failed"))} />
      {copied === "ok" && (
        <p style={{ textAlign: "center", color: "#3fb950" }}>
          Copied ✔ — <code>{PROVISION_CMD}</code></p>
      )}
      {copied === "failed" && (
        <p style={{ textAlign: "center", color: "#e3b341" }}>
          Copy failed — run <code>{PROVISION_CMD}</code> yourself.</p>
      )}
    </div>
  );
}
