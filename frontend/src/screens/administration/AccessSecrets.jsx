import React, { useEffect, useState } from "react";
import { api, simState } from "../../api.js";
import { HudFrame } from "../../ui/HudFrame.jsx";
import { Button } from "../../ui/Button.jsx";
import { Status } from "../../ui/Status.jsx";
import { AsyncRegion } from "../../ui/AsyncRegion.jsx";
import { T1Overlay } from "../../Tiers.jsx";
import { performHardwareTouch } from "../../webauthn.js";
import { adminHref, defaultActionHandlers, hudGet, hudPost, parseHashQuery, writeHashQuery } from "./contract.js";
import { CollectionScreen } from "./CollectionScreen.jsx";
import { useHudLoad } from "./useHudLoad.js";

const SECRET_KEYS = ["plaintext", "ciphertext", "wrapped_dek", "nonce", "private_url", "value"];
const TABS = [
  { id: "vault", label: "Vault" },
  { id: "members", label: "Members" },
  { id: "roles", label: "Roles" },
  { id: "sessions", label: "Sessions" },
  { id: "security", label: "Security" },
];

export function secretLeakFields(record) {
  if (!record || typeof record !== "object") return [];
  return SECRET_KEYS.filter((k) => Object.prototype.hasOwnProperty.call(record, k) && record[k]);
}

export async function fetchRotatePlan(secretId) {
  return api(`v1/hud/secrets/${secretId}/rotate-plan/`);
}

export function attachSecretActions(rows, { onPlanRotation } = {}) {
  return (rows || []).map((row) => ({
    ...row,
    allowed_actions: (row.allowed_actions || []).map((a) => ({
      ...a,
      onRun: a.id === "secret.rotate_plan"
        ? async () => {
            const { status, data } = await fetchRotatePlan(row.id);
            if (status === 200) onPlanRotation?.(data);
          }
        : a.onRun,
    })),
  }));
}

export function AccessSecretsView({
  rows = [],
  selectedId,
  onSelect,
  members = [],
  memberDisabled = [],
  query = "",
  onQuery,
  width = 1280,
  phase = "live",
  error,
  onRetry,
  rotation,
  onPlanRotation,
  tab = "vault",
  onTab,
  collectionActions,
  sessions = [],
  roles = [],
  onNav,
  wizard,
  onWizardSubmit,
  lastCommand,
  onReloadPermissions,
}) {
  const selected = rows.find((r) => String(r.id) === String(selectedId));
  const [secretPending, setSecretPending] = useState(null);
  const [secretTouched, setSecretTouched] = useState(false);
  if (phase === "permission-denied" || phase === "signed-out") {
    return (
      <AsyncRegion
        phase={phase}
        deniedReason="Administration read capability required."
        onReloadPermissions={onReloadPermissions}
        onReturnToOperator={() => onNav?.("home")}
      />
    );
  }
  const leaks = rows.flatMap(secretLeakFields);
  const wired = attachSecretActions(rows, { onPlanRotation });
  const handlers = defaultActionHandlers({
    onNav,
    onCommand: async (cmd) => {
      if (cmd.path?.includes("rotate-plan")) {
        const { status, data } = await api(cmd.path);
        if (status === 200) onPlanRotation?.(data);
        return { status, data };
      }
      return hudPost(cmd.path, cmd.body);
    },
  });
  const actions = (collectionActions || [
    { id: "secret.create", label: "ADD SECRET" },
    { id: "member.invite", label: "INVITE USER" },
    { id: "secret.rotate", label: "ROTATE" },
    { id: "secret.rotate_queue", label: "REVIEW ROTATION PLAN" },
  ]).map((a) => ({
    ...a,
    onRun: a.onRun || (() => handlers[a.id]?.(selected || a)),
  }));
  const columns = [
    { id: "kind", label: "Kind" },
    { id: "owner_type", label: "Owner type" },
    { id: "owner_id", label: "Owner" },
    { id: "fingerprint", label: "Fingerprint" },
    { id: "actions", label: "Actions" },
  ];
  return (
    <div>
      <div className="hud-toolbar">
        <h1 className="hud-title">Access &amp; Secrets</h1>
        {actions.filter((a) => {
          if (tab === "vault") return a.id.startsWith("secret");
          if (tab === "members") return a.id.startsWith("member");
          return false;
        }).map((a) => (
          <Button
            key={a.id}
            variant={a.id === "secret.create" ? "primary" : "secondary"}
            onClick={() => a.onRun?.(a)}
          >
            {a.label}
          </Button>
        ))}
      </div>
      <p className="hud-kicker">Metadata only — values never enter this view</p>
      {leaks.length ? <p role="alert">Secret material leaked into the view.</p> : null}
      <div className="hud-facets" role="tablist" aria-label="Access domains">
        {TABS.map((item) => (
          <Button
            key={item.id}
            variant={tab === item.id ? "primary" : "quiet"}
            onClick={() => onTab?.(item.id)}
          >
            {item.label}
          </Button>
        ))}
      </div>
      {tab === "vault" ? (
        <CollectionScreen
          caption="Vault inventory"
          columns={columns}
          rows={wired}
          filters={{ q: query }}
          onFilter={(next) => onQuery?.(next.q)}
          filterDefs={[{ id: "q", label: "Search kinds and owners", type: "text" }]}
          selectedId={selectedId}
          onSelect={onSelect}
          onNav={onNav}
          phase={phase}
          error={error}
          onRetry={onRetry}
          width={width}
          emptySentence="No secrets recorded — store credentials through the vault, never in git."
          emptyButton="Open Settings"
          onEmpty={() => onNav?.("settings")}
          inspector={selected ? {
            body: (
              <div>
                <p>{selected.kind} on {selected.owner_type}:{selected.owner_id}</p>
                <p>Fingerprint {selected.fingerprint}</p>
                <Status state={selected.lifecycle || "active"} />
                <h3 className="hud-kicker">Affected objects</h3>
                <ul>
                  {(selected.references || []).map((r) => (
                    <li key={`${r.type}-${r.id}`}>{r.type} {r.name || r.id}</li>
                  ))}
                </ul>
                <Button
                  variant="primary"
                  onClick={async () => {
                    const { status, data } = await fetchRotatePlan(selected.id);
                    if (status === 200) onPlanRotation?.(data);
                  }}
                >
                  ROTATE
                </Button>
                {rotation ? (
                  <p>
                    Rotation plan names: {(rotation.affected || rotation).map((x) => x.name || x).join(", ")}
                  </p>
                ) : null}
                {(selected.disabled_actions || []).map((a) => (
                  <Button key={a.id} disabled disabledReason={a.reason}>{a.label}</Button>
                ))}
              </div>
            ),
          } : null}
          inspectorTitle="Secret inspector"
        />
      ) : null}
      {tab === "members" ? (
        <HudFrame variant="panel">
          <h2 className="hud-kicker">Members</h2>
          <ul>
            {members.map((m) => <li key={m.id}>{m.username} — {m.role}</li>)}
          </ul>
          {memberDisabled.map((a) => (
            <Button key={a.id} disabled disabledReason={a.reason}>{a.label}</Button>
          ))}
        </HudFrame>
      ) : null}
      {tab === "roles" ? (
        <HudFrame variant="panel">
          <h2 className="hud-kicker">Roles</h2>
          <p>Viewer, Auditor, Operator, Deployer, Admin, Owner — capabilities are server-enforced.</p>
          <ul>
            {(roles.length ? roles : members).map((m) => (
              <li key={m.id}>{m.username || m.name} — {m.role}</li>
            ))}
          </ul>
        </HudFrame>
      ) : null}
      {tab === "sessions" ? (
        <HudFrame variant="panel">
          <h2 className="hud-kicker">Sessions</h2>
          {(sessions.length ? sessions : [{ id: "current", label: "This browser session" }]).map((s) => (
            <p key={s.id}>{s.label || s.id}</p>
          ))}
        </HudFrame>
      ) : null}
      {tab === "security" ? (
        <HudFrame variant="panel">
          <h2 className="hud-kicker">Security</h2>
          <p>Passkeys, TOTP fallback, and recovery codes are managed per member. Secret values stay in Vault.</p>
          {members.map((m) => (
            <p key={m.id}>{m.username} — passkeys {m.passkeys ?? "unknown"} — TOTP {m.totp ? "yes" : "no"} — recovery {m.recovery_codes ?? "unknown"}</p>
          ))}
        </HudFrame>
      ) : null}
      {wizard === "secret" ? (
        <HudFrame variant="panel">
          <h2 className="hud-kicker">ADD SECRET</h2>
          <p>Value is accepted once over a protected input and is never returned.</p>
          {secretPending ? (
            <T1Overlay
              label="Store secret"
              summary="T1 — type the owner id and touch a security key."
              onTouch={async () => {
                if (simState()) {
                  setSecretTouched(true);
                  return;
                }
                const result = await performHardwareTouch();
                if (result?.status === 200) setSecretTouched(true);
              }}
              onConfirm={({ name }) => {
                if (!secretTouched || !name || name !== String(secretPending.owner_id || "")) {
                  return false;
                }
                onWizardSubmit?.("secret", secretPending);
                setSecretPending(null);
                setSecretTouched(false);
                return true;
              }}
              onDismiss={() => { setSecretPending(null); setSecretTouched(false); }}
            />
          ) : (
            <form className="hud-filter" onSubmit={(e) => {
              e.preventDefault();
              setSecretTouched(false);
              setSecretPending(Object.fromEntries(new FormData(e.target)));
            }}>
              <label>Kind
                <select name="kind" aria-label="Secret kind" defaultValue="api_token">
                  <option value="api_token">api_token</option>
                  <option value="cloud_credential">cloud_credential</option>
                  <option value="backup_key">backup_key</option>
                </select>
              </label>
              <label>Owner type
                <select name="owner_type" aria-label="Owner type" defaultValue="site">
                  <option value="site">site</option>
                  <option value="dns_account">dns_account</option>
                  <option value="aws">aws</option>
                </select>
              </label>
              <label>Owner
                <select name="owner_id" aria-label="Owner id">
                  {(rows || []).map((r) => (
                    <option key={r.id} value={r.owner_id}>{r.owner_type}:{r.owner_id}</option>
                  ))}
                </select>
              </label>
              <label>Value<input name="value" type="password" aria-label="Secret value" /></label>
              <Button type="submit" variant="primary">Store secret</Button>
            </form>
          )}
        </HudFrame>
      ) : null}
      {wizard === "invite" ? (
        <HudFrame variant="panel">
          <h2 className="hud-kicker">INVITE USER</h2>
          <form className="hud-filter" onSubmit={(e) => { e.preventDefault(); onWizardSubmit?.("invite", Object.fromEntries(new FormData(e.target))); }}>
            <label>Username<input name="username" aria-label="Invite username" /></label>
            <label>Email<input name="email" type="email" aria-label="Invite email" /></label>
            <label>Role
              <select name="role" aria-label="Invite role" defaultValue="operator">
                <option value="viewer">viewer</option>
                <option value="auditor">auditor</option>
                <option value="operator">operator</option>
                <option value="deployer">deployer</option>
                <option value="admin">admin</option>
              </select>
            </label>
            <Button type="submit" variant="primary">Send invitation</Button>
          </form>
        </HudFrame>
      ) : null}
      {lastCommand ? <p>Last command accepted {lastCommand.operation_id || lastCommand.secret_id || lastCommand.invitation_id}</p> : null}
    </div>
  );
}

export default function AccessSecrets({ route, onNav, width, onReloadPermissions }) {
  const [query, setQuery] = useState("");
  const [rotation, setRotation] = useState(null);
  const [lastCommand, setLastCommand] = useState(null);
  const selectedId = route?.id?.includes("/") ? route.id.split("/")[1] : undefined;
  const hashQ = { ...(route?.query || {}), ...parseHashQuery(undefined, { tab: "vault" }) };
  const tab = hashQ.tab || "vault";
  const wizard = hashQ.wizard;
  const { phase, data, error, retry } = useHudLoad(
    async () => {
      const [secrets, mem] = await Promise.all([
        hudGet("v1/hud/secrets/"),
        hudGet("v1/hud/members/"),
      ]);
      return { secrets, members: mem };
    },
    [hashQ.scope],
  );
  const rows = data?.secrets?.results || [];

  useEffect(() => {
    const rotateId = hashQ.rotate || (hashQ.plan === "queue" ? rows[0]?.id : null);
    if (!rotateId) return undefined;
    let cancelled = false;
    fetchRotatePlan(rotateId).then(({ status, data: plan }) => {
      if (!cancelled && status === 200) setRotation(plan);
    });
    return () => { cancelled = true; };
  }, [hashQ.rotate, hashQ.plan, rows]);

  const visible = rows.filter((r) => {
    if (!query) return true;
    const hay = `${r.kind} ${r.owner_type} ${r.owner_id} ${r.fingerprint}`.toLowerCase();
    return hay.includes(query.toLowerCase());
  });

  return (
    <AccessSecretsView
      rows={visible}
      selectedId={selectedId}
      onSelect={(id) => onNav("admin", id ? `secrets/${id}` : "secrets")}
      members={data?.members?.results || []}
      memberDisabled={data?.members?.disabled_actions || []}
      query={query}
      onQuery={setQuery}
      width={width}
      phase={phase}
      error={error}
      onRetry={retry}
      onReloadPermissions={onReloadPermissions || retry}
      rotation={rotation}
      onPlanRotation={setRotation}
      tab={tab}
      onNav={onNav}
      wizard={wizard}
      lastCommand={lastCommand}
      onWizardSubmit={async (kind, fields) => {
        if (kind === "secret") {
          const { status, data: body } = await hudPost("v1/hud/secrets/", fields);
          if (status === 201 || status === 202) setLastCommand(body);
          return;
        }
        const { status, data: body } = await hudPost("v1/hud/members/", fields);
        if (status === 201 || status === 202) setLastCommand(body);
      }}
      onTab={(next) => {
        onNav("admin", adminHref("secrets", { tab: next }));
        writeHashQuery({ tab: next }, undefined, "#/admin/secrets");
      }}
    />
  );
}
