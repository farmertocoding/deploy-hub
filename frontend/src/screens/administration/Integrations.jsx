import React, { useEffect, useState } from "react";
import { HudFrame } from "../../ui/HudFrame.jsx";
import { Button } from "../../ui/Button.jsx";
import { Status } from "../../ui/Status.jsx";
import { AsyncRegion } from "../../ui/AsyncRegion.jsx";
import { currentScope, defaultActionHandlers, hudGet, hudPost } from "./contract.js";

export function IntegrationsView({
  data = {},
  phase = "live",
  error,
  onRetry,
  asOf,
  deniedReason,
  onNav,
  onCommand,
  lastCommand,
}) {
  if (phase !== "live" && phase !== "degraded") {
    return (
      <AsyncRegion
        phase={phase}
        what="integrations"
        error={error}
        onRetry={onRetry}
        deniedReason={deniedReason}
      />
    );
  }
  const aws = data.aws || {};
  const cf = data.cloudflare || {};
  const dns = data.dns || [];
  const vault = data.vault || {};
  const handlers = defaultActionHandlers({
    onNav,
    onCommand: async (cmd) => {
      const result = await hudPost(cmd.path, cmd.body);
      onCommand?.(result.data);
      return result;
    },
  });
  return (
    <AsyncRegion phase={phase} asOf={asOf} what="integrations">
      <h1 className="hud-title">Integrations &amp; DNS</h1>
      <div className="hud-grid-2">
        <HudFrame variant="panel">
          <h2 className="hud-kicker">AWS</h2>
          <p><Status state={aws.state || "pending"} /> account ···{aws.account_last4 || "—"} {aws.region}</p>
          <Button variant="navigation" onClick={() => handlers["aws.verify"]()}>Verify again</Button>
          <Button onClick={() => handlers[aws.state === "connected" ? "aws.replace" : "aws.connect"]()}>
            {aws.state === "connected" ? "Replace credentials" : "Connect"}
          </Button>
        </HudFrame>
        <HudFrame variant="panel">
          <h2 className="hud-kicker">Cloudflare</h2>
          <p><Status state={cf.state || "pending"} /> {cf.account || "not connected"}</p>
          <Button variant="navigation" onClick={() => handlers["cloudflare.verify"]()}>Verify token</Button>
          <Button onClick={() => handlers[cf.state === "connected" ? "cloudflare.replace" : "cloudflare.connect"]()}>
            {cf.state === "connected" ? "Replace token" : "Connect"}
          </Button>
        </HudFrame>
      </div>
      <HudFrame variant="panel">
        <h2 className="hud-kicker">DNS accounts and zones</h2>
        {dns.length === 0 ? <p>No DNS accounts connected.</p> : dns.map((z) => (
          <p key={z.id}>{z.provider} — {z.label} ({z.zones || 0} zones)</p>
        ))}
        <Button onClick={() => handlers["dns.add_zone"]()}>Add zone</Button>
        <Button variant="navigation" onClick={() => handlers["dns.verify"]()}>Verify</Button>
      </HudFrame>
      <HudFrame variant="panel">
        <h2 className="hud-kicker">Vault</h2>
        <p>KEK {vault.kek_id || "unset"} · {vault.kek_age_days ?? "—"} days · {vault.active_secrets || 0} active secrets</p>
        <Button variant="navigation" onClick={() => handlers["secret.rotate_queue"]()}>REVIEW ROTATION PLAN</Button>
      </HudFrame>
      {lastCommand ? <p>Last command {lastCommand.action} {lastCommand.operation_id}</p> : null}
    </AsyncRegion>
  );
}

export default function Integrations({ onNav, route }) {
  const [data, setData] = useState({});
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  const [asOf, setAsOf] = useState(null);
  const [lastCommand, setLastCommand] = useState(null);
  const [tick, setTick] = useState(0);
  const scope = currentScope(route);
  useEffect(() => {
    let cancelled = false;
    hudGet("v1/hud/integrations/", route).then((body) => {
      if (cancelled) return;
      setData(body);
      setAsOf(body.observed_at);
      setPhase("live");
    }).catch((err) => {
      if (cancelled) return;
      setPhase(err.denied ? "permission-denied" : err.signedOut ? "signed-out" : "error");
      setError(err?.data?.detail || "HTTP error");
    });
    return () => { cancelled = true; };
  }, [scope, tick]);
  return (
    <IntegrationsView
      data={data}
      phase={phase}
      error={error}
      asOf={asOf}
      onRetry={() => setTick((n) => n + 1)}
      onNav={onNav}
      onCommand={setLastCommand}
      lastCommand={lastCommand}
    />
  );
}
