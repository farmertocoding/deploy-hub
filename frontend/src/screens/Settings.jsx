// Settings (§F1): the non-object surfaces, as TABS — Cloudflare (Task 12b:
// paste a single-zone token), Developer (the Phase-0 demo pane, a plumbing
// proof and not the product surface), and Vault (a Settings tab until Phase 4
// gives it a real screen).
//
// The demo pane is otherwise the Phase-0 code moved verbatim, with two changes:
// it takes the shell's ONE events client as a prop instead of opening a second
// socket, and its Launch goes through the §F5 tier machinery — demo.launch is a T2
// row, so the confirm dialog summarizing what will run is the live wiring of the
// tier table to the one mutating action the product has today.
import React, { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { schemas } from "../api/zod.ts";
import { api } from "../api.js";
import { presentation, tierFor } from "../actions.js";
import { ActionButton, ConfirmDialog } from "../Tiers.jsx";
import { registerPasskey } from "../webauthn.js";

import { box } from "../ui/surface.js";

export const SETTINGS_TABS = [
  { id: "security", label: "Security" },
  { id: "cloudflare", label: "Cloudflare" },
  { id: "aws", label: "AWS" },
  { id: "partners", label: "Partners" },
  { id: "developer", label: "Developer" },
  { id: "vault", label: "Vault" },
];

export async function connectCloudflare(token) {
  return api("v1/cloudflare/connect/", { token });
}

export async function plantOriginCa(accountId, path) {
  return api(`v1/dns-accounts/${accountId}/origin-ca-plant/`, { path });
}

export function connectedCloudflareAccounts(data) {
  return (Array.isArray(data?.dns) ? data.dns : [])
    .filter((row) => row?.provider === "cloudflare" && row?.id != null);
}

export async function connectAws(access_key_id, secret_access_key) {
  return api("v1/aws/connect/", { access_key_id, secret_access_key });
}

export async function awsStatus() {
  return api("v1/aws/connect/");
}

export async function partnersList() {
  return api("v1/partners/");
}

export async function createPartner(slug, confirmName) {
  return api("v1/partners/", {
    slug,
    name: slug,
    confirm_name: confirmName,
  });
}

export async function suspendPartner(partnerId, confirmName) {
  return api(`v1/partners/${partnerId}/suspend/`, { confirm_name: confirmName });
}

export async function killPartnerApi(confirmName, enabled) {
  return api("v1/partner-api/kill-switch/", { confirm_name: confirmName, enabled });
}

export async function rankPartnerDestination(partnerId, destinationOrder) {
  return api(`v1/partners/${partnerId}/destination-rank/`, {
    destination_order: destinationOrder,
  });
}

export const OWN_SERVER_HONESTY =
  "abuse takedowns and IP-reputation damage land on hardware and residential/office connections you cannot dispose of";

export function addDestination(order, targetId) {
  const id = Number(targetId);
  if (!id || (order || []).includes(id)) return list(order);
  return [...list(order), id];
}
export function moveDestination(order, targetId, dir) {
  const next = list(order);
  const i = next.indexOf(Number(targetId));
  const j = i + Number(dir);
  if (i < 0 || j < 0 || j >= next.length) return next;
  const copy = next.slice();
  const [row] = copy.splice(i, 1);
  copy.splice(j, 0, row);
  return copy;
}
export function removeDestination(order, targetId) {
  return list(order).filter((id) => id !== Number(targetId));
}
function list(order) { return Array.isArray(order) ? order.slice() : []; }

function destLookup(partner, candidates) {
  const byId = new Map();
  for (const row of [...(partner?.destinations || []), ...(candidates || [])]) {
    if (row?.id != null) byId.set(Number(row.id), row);
  }
  return byId;
}

export function intakeLine(intake) {
  const stamp = intake?.as_of
    ? ` · data as of ${new Date(intake.as_of).toLocaleTimeString([], { hour12: false })}`
    : "";
  if (intake?.status === "error") return `Intake error${stamp}`;
  const fake = intake?.mode === "fake" || !intake?.configured ? "Fake intake" : "Intake";
  return `⚠ degraded — ${fake}${stamp}`;
}

export function PartnerEnrollOnce({ hubk, whsec, onSaved }) {
  const [copied, setCopied] = useState(false);
  const blob = `${hubk}\n${whsec}`;
  return (
    <div role="dialog" aria-label="Enroll once" style={{ ...box, marginTop: 8 }}>
      <h3 style={{ marginTop: 0 }}>Partner keys — shown once</h3>
      <p>Copy these now. Closing this panel loses them; GET will never return them.</p>
      <pre style={{ ...box, lineHeight: 1.8 }}>{hubk}{"\n"}{whsec}</pre>
      <button style={{ ...box, marginRight: 8 }}
        onClick={() => {
          const clip = typeof navigator !== "undefined" ? navigator.clipboard : null;
          if (!clip?.writeText) { setCopied("failed"); return; }
          clip.writeText(blob).then(() => setCopied("ok"), () => setCopied("failed"));
        }}>
        {copied === "ok" ? "Copied ✔"
          : copied === "failed" ? "Copy failed — select the keys manually"
          : "Copy"}
      </button>
      <button style={box} onClick={onSaved}>I saved them</button>
    </div>
  );
}

export function PartnersPanel({
  partners: partnersProp,
  intake: intakeProp,
  minted: mintedProp,
  apiEnabled: apiEnabledProp,
  candidateTargets: candidateTargetsProp,
  rankDrafts: rankDraftsProp,
  systemAdmin = false,
}) {
  const [partners, setPartners] = useState(partnersProp ?? []);
  const [intake, setIntake] = useState(
    intakeProp ?? { status: "degraded", mode: "fake", configured: false },
  );
  const [minted, setMinted] = useState(mintedProp ?? null);
  const [apiEnabled, setApiEnabled] = useState(Boolean(apiEnabledProp));
  const [candidateTargets, setCandidateTargets] = useState(candidateTargetsProp ?? []);
  const [drafts, setDrafts] = useState(() => {
    if (rankDraftsProp !== undefined) return { ...rankDraftsProp };
    const out = {};
    for (const p of partnersProp ?? []) {
      out[p.id] = list(p.destination_order);
    }
    return out;
  });
  const [addPick, setAddPick] = useState({});

  useEffect(() => {
    if (partnersProp !== undefined) return undefined;
    partnersList().then(({ status, data }) => {
      if (status === 200) {
        const rows = data.partners || [];
        setPartners(rows);
        setIntake(data.intake || {
          status: "degraded", mode: "fake", configured: false,
        });
        setApiEnabled(Boolean(data.api_enabled));
        setCandidateTargets(data.candidate_targets || []);
        setDrafts((prev) => {
          const next = { ...prev };
          for (const row of rows) {
            if (next[row.id] === undefined) next[row.id] = list(row.destination_order);
          }
          return next;
        });
      }
    });
    return undefined;
  }, [partnersProp]);

  async function refreshList() {
    const listed = await partnersList();
    if (listed.status === 200) {
      setPartners(listed.data.partners || []);
      setIntake(listed.data.intake || intake);
      setApiEnabled(Boolean(listed.data.api_enabled));
      setCandidateTargets(listed.data.candidate_targets || []);
    }
  }

  async function runCreate(args) {
    const slug = (args?.name || "").trim();
    const { status, data } = await createPartner(slug, slug);
    if (status !== 201) return;
    setMinted({ hubk: data.hubk, whsec: data.whsec });
    await refreshList();
  }

  async function runKillSwitch(args) {
    const { status, data } = await killPartnerApi(
      args?.name || "partner-api",
      !apiEnabled,
    );
    if (status === 200) setApiEnabled(Boolean(data?.api_enabled));
  }

  async function runSuspend(partner, args) {
    await suspendPartner(partner.id, args?.name || partner.slug);
    await refreshList();
  }

  async function runRank(partner) {
    const order = drafts[partner.id] ?? partner.destination_order ?? [];
    await rankPartnerDestination(partner.id, order);
    await refreshList();
  }

  const empty = partners.length === 0 && !minted;
  const killRow = {
    ...tierFor("partner.api_kill_switch"),
    label: apiEnabled ? "Disable partner API" : "Enable partner API",
  };
  return (
    <div style={{ maxWidth: 720 }}>
      <h2>Partners</h2>
      <p style={{ color: "var(--hud-warning)" }}>{intakeLine(intake)}</p>
      <p>Fake / empty INTAKE_URL is degraded. Partner intake SLA is
        response-time, not uptime.</p>
      {minted && (
        <PartnerEnrollOnce hubk={minted.hubk} whsec={minted.whsec}
          onSaved={() => setMinted(null)} />
      )}
      {empty && (
        <p>No partners yet — create a partner to mint Hub keys.</p>
      )}
      {partners.map((p) => {
        const order = drafts[p.id] ?? list(p.destination_order);
        const byId = destLookup(p, candidateTargets);
        const inDraft = new Set(order.map(Number));
        const available = (candidateTargets || []).filter(
          (c) => !inDraft.has(Number(c.id)),
        );
        const includesSsh = order.some((id) => byId.get(Number(id))?.kind === "ssh");
        return (
        <div key={p.id} style={{ ...box, marginBottom: 8 }}>
          <strong>{p.slug}</strong>
          {p.suspended ? <span> Suspended</span> : null}
          <div>
            {order.length === 0
              ? "Destination order is empty — partner-site create will refuse. Default: dedicated cloud first."
              : "Default: dedicated cloud first."}
          </div>
          {order.map((id) => (
            <div key={id}>
              {byId.get(Number(id))?.host || id}
              {" "}
              <button type="button" style={box}
                onClick={() => setDrafts((d) => ({
                  ...d,
                  [p.id]: moveDestination(d[p.id] ?? list(p.destination_order), id, -1),
                }))}>Up</button>
              <button type="button" style={box}
                onClick={() => setDrafts((d) => ({
                  ...d,
                  [p.id]: moveDestination(d[p.id] ?? list(p.destination_order), id, 1),
                }))}>Down</button>
              <button type="button" style={box}
                onClick={() => setDrafts((d) => ({
                  ...d,
                  [p.id]: removeDestination(d[p.id] ?? list(p.destination_order), id),
                }))}>Remove</button>
            </div>
          ))}
          <div>
            <select aria-label="Add destination" style={box}
              value={addPick[p.id] ?? ""}
              onChange={(e) => setAddPick((s) => ({ ...s, [p.id]: e.target.value }))}>
              <option value="" />
              {available.map((c) => (
                <option key={c.id} value={c.id}>{c.host}</option>
              ))}
            </select>
            <button type="button" style={box}
              onClick={() => {
                setDrafts((d) => ({
                  ...d,
                  [p.id]: addDestination(d[p.id] ?? list(p.destination_order), addPick[p.id]),
                }));
                setAddPick((s) => ({ ...s, [p.id]: "" }));
              }}>Add destination</button>
          </div>
          <ActionButton row={tierFor("partner.suspend")}
            confirmName={p.slug}
            summary="Stop containers, detach routes, revoke the Hub-side key."
            onRun={(args) => runSuspend(p, args)} />
          {/* Suspend partner — stop containers / detach routes / revoke key. */}
          <ActionButton row={tierFor("partner.destination_rank")}
            summary={includesSsh
              ? "abuse takedowns and IP-reputation damage land on hardware and residential/office connections you cannot dispose of"
              : "Default: dedicated cloud first."}
            onRun={() => runRank(p)} />
          {/* Own-server kind === "ssh" confirm is the K5 honesty sentence once. */}
        </div>
        );
      })}
      {!minted && (
        <ActionButton row={tierFor("partner.create")}
          onRun={runCreate} />
      )}
      {systemAdmin ? (
        <ActionButton row={killRow} confirmName="partner-api"
          onRun={runKillSwitch} />
      ) : null}
      {/* Create partner — mint keys, not a paste form. Enable is T1 not a toggle. */}
    </div>
  );
}

export function AwsStatusBanner({ connected, reason, accountLast4, region }) {
  if (connected || accountLast4) {
    if (!accountLast4 || !region) return null;
    return (
      <div style={{ color: "var(--hud-success)", marginTop: 8 }}>
        Account ···{accountLast4} in {region}.
      </div>
    );
  }
  return (
    <div style={{ color: "var(--hud-warning)", marginBottom: 8 }}>
      AWS is not connected. {reason}
    </div>
  );
}

export function AwsPanel({ systemAdmin = false } = {}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [awsOk, setAwsOk] = useState(false);
  const [statusReason, setStatusReason] = useState("set HUB_AWS_CREDENTIALS_REF");
  const {
    register, handleSubmit, setError, reset, clearErrors,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(schemas.AwsConnect),
    defaultValues: { access_key_id: "", secret_access_key: "" },
  });

  useEffect(() => {
    awsStatus().then(({ data }) => {
      setAwsOk(Boolean(data?.connected));
      setStatusReason(data?.reason || "set HUB_AWS_CREDENTIALS_REF");
    });
  }, []);

  async function submit(values) {
    if (busy) return;
    setBusy(true);
    setResult(null);
    clearErrors();
    const { status, data } = await connectAws(
      values.access_key_id, values.secret_access_key,
    );
    setBusy(false);
    if (status === 201) {
      const parsed = schemas.AwsConnectResult.safeParse(data);
      setResult(parsed.success ? parsed.data : data);
      setAwsOk(true);
      reset({ access_key_id: "", secret_access_key: "" });
      return;
    }
    const field = Object.values(data.errors ?? {}).flat()[0];
    const message = field?.message ?? data.detail ?? data.reason
      ?? `Unexpected ${status} response.`;
    setAwsOk(false);
    setStatusReason(message);
    setError("root", { type: field?.code ?? String(status), message });
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <h2>AWS</h2>
      <p>Paste an IAM user access key. The Hub observes GetCallerIdentity and
        the C4 allowlist (user <em>and</em> groups) before any vault write —
        the secret never comes back. Unconfigured is degraded: set
        <code> HUB_AWS_CREDENTIALS_REF</code>.</p>
      <AwsStatusBanner
        connected={awsOk}
        reason={statusReason}
        accountLast4={result?.account_id_last4}
        region={result?.region}
      />
      {!systemAdmin && (
        <p>Connecting AWS credentials is a system-administrator action.</p>
      )}
      {systemAdmin && (
        <>
          <form onSubmit={handleSubmit(submit)}
            style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
            <label style={{ display: "grid", gap: 4, flex: "1 1 240px" }}>
              <small>access key id</small>
              <input type="password" {...register("access_key_id")} style={box}
                autoComplete="off" aria-invalid={!!errors.access_key_id} />
            </label>
            <label style={{ display: "grid", gap: 4, flex: "1 1 240px" }}>
              <small>secret access key</small>
              <input type="password" {...register("secret_access_key")} style={box}
                autoComplete="off" aria-invalid={!!errors.secret_access_key} />
            </label>
            <ActionButton
              row={tierFor("aws.connect")}
              confirmName="aws"
              onRun={() => handleSubmit(submit)()}
            />
          </form>
          {errors.root && (
            <div style={{ color: "var(--hud-danger)", marginTop: 8 }}>{errors.root.message}</div>
          )}
        </>
      )}
    </div>
  );
}

export function CloudflarePanel() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [accountId, setAccountId] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [planted, setPlanted] = useState(false);
  const [plantBusy, setPlantBusy] = useState(false);
  const {
    register, handleSubmit, setError, reset, clearErrors,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(schemas.CloudflareConnect),
    defaultValues: { token: "" },
  });
  const plantForm = useForm({
    resolver: zodResolver(schemas.OriginCaPlant),
    defaultValues: { path: "" },
  });

  useEffect(() => {
    let cancelled = false;
    api("v1/hud/integrations/").then(({ status, data }) => {
      if (cancelled || status !== 200) return;
      const connected = connectedCloudflareAccounts(data);
      setAccounts(connected);
      if (connected.length === 1) setAccountId(connected[0].id);
    });
    return () => { cancelled = true; };
  }, []);

  async function submit(values) {
    if (busy) return;
    setBusy(true);
    setResult(null);
    clearErrors();
    const { status, data } = await connectCloudflare(values.token);
    setBusy(false);
    if (status === 201) {
      const parsed = schemas.CloudflareConnectResult.safeParse(data);
      const body = parsed.success ? parsed.data : data;
      setResult(body);
      setAccountId(body.account?.id ?? null);
      if (body.account?.id != null) {
        setAccounts((rows) => [
          ...rows.filter((row) => String(row.id) !== String(body.account.id)),
          body.account,
        ]);
      }
      setPlanted(false);
      reset({ token: "" });
      return;
    }
    const field = Object.values(data.errors ?? {}).flat()[0];
    setError("token", {
      type: field?.code ?? String(status),
      message: field?.message ?? data.detail ?? `Unexpected ${status} response.`,
    });
  }

  async function submitPlant(values) {
    if (plantBusy || accountId == null) return;
    setPlantBusy(true);
    plantForm.clearErrors();
    const { status, data } = await plantOriginCa(accountId, values.path);
    setPlantBusy(false);
    if (status === 200) {
      const parsed = schemas.OriginCaPlantResult.safeParse(data);
      setPlanted(parsed.success ? parsed.data.planted : Boolean(data.planted));
      return;
    }
    const field = Object.values(data.errors ?? {}).flat()[0];
    plantForm.setError("path", {
      type: field?.code ?? String(status),
      message: field?.message ?? data.detail ?? `Unexpected ${status} response.`,
    });
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <h2>Cloudflare</h2>
      <p>Paste a single-zone API token. The Hub verifies it and stores it in the
        vault — the token never comes back. This screen stores a DNS token only;
        Origin certificates refuse until <code>origin_ca_key_ref</code> is set
        on the account in the vault. Plant a Bearer API token with Zone → SSL
        and Certificates → Edit; it does not accept a paste, and it does not
        accept a deprecated Origin CA service key.</p>
      <form onSubmit={handleSubmit(submit)}
        style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
        <label style={{ display: "grid", gap: 4, flex: "1 1 240px" }}>
          <small>API token</small>
          <input type="password" {...register("token")} style={box}
            autoComplete="off" aria-invalid={!!errors.token} />
        </label>
        <ActionButton
          row={tierFor("dns.cloudflare_connect")}
          confirmName="cloudflare"
          onRun={() => handleSubmit(submit)()}
        />
      </form>
      {errors.token && (
        <div style={{ color: "var(--hud-danger)", marginTop: 8 }}>{errors.token.message}</div>
      )}
      {result && (
        <div style={{ color: "var(--hud-success)", marginTop: 8 }}>
          Connected {result.account?.label} — zone {result.zone?.name}
          {result.zone?.purpose ? ` (${result.zone.purpose})` : ""}.
        </div>
      )}
      <h3 style={{ marginTop: 24 }}>Origin-CA plant</h3>
      <p>Plant status: {planted ? "planted" : "not planted"}. Hub-local path
        only — under <code>/etc/deploy-hub/origin-ca/</code> or
        <code>/var/lib/deploy-hub/origin-ca/</code>. The file must be a Bearer
        token with Zone SSL and Certificates Edit, not a v1.0- service key.
        The Hub reads the file; do not paste token bytes here.</p>
      <form onSubmit={plantForm.handleSubmit(submitPlant)}
        style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
        <label style={{ display: "grid", gap: 4, flex: "1 1 200px" }}>
          <small>DNS account</small>
          <select aria-label="Origin-CA DNS account" value={accountId ?? ""}
            onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}
            style={box}>
            <option value="">select an account</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.label || `Cloudflare account ${account.id}`}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: "grid", gap: 4, flex: "1 1 240px" }}>
          <small>path</small>
          <input type="text" {...plantForm.register("path")} style={box}
            autoComplete="off" aria-invalid={!!plantForm.formState.errors.path} />
        </label>
        <ActionButton
          row={tierFor("dns.origin_ca_plant")}
          confirmName="origin-ca"
          onRun={() => plantForm.handleSubmit(submitPlant)()}
        />
      </form>
      {plantForm.formState.errors.path && (
        <div style={{ color: "var(--hud-danger)", marginTop: 8 }}>
          {plantForm.formState.errors.path.message}
        </div>
      )}
    </div>
  );
}

export function SecurityPanel({ user }) {
  const [qr, setQr] = useState(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [recovery, setRecovery] = useState(null);

  async function startTotp() {
    const { status, data } = await api("auth/totp/enroll/", {});
    if (status === 201) setQr(data);
    else setError(data.detail || "TOTP enrollment failed to start");
  }
  async function confirmTotp(e) {
    e.preventDefault();
    const { status, data } = await api("auth/totp/confirm/", { otp_code: code });
    if (status === 200) setRecovery(data.recovery_codes);
    else setError(data.detail || "Code did not verify");
  }
  async function addPasskey() {
    const { status, data } = await registerPasskey("phone");
    if (status !== 200 && status !== 201) {
      setError(data.detail || "Passkey enrollment failed to start");
    }
  }

  return (
    <div style={{ maxWidth: 520 }}>
      <h2>Security</h2>
      <p>Passkeys are primary. TOTP is a fallback for login, never for T1.</p>
      <p style={{ color: "var(--hud-muted)" }}>
        Signed in as {user?.username}. T1 needs two passkeys
        {user?.webauthn_count != null ? ` (enrolled: ${user.webauthn_count})` : ""}.
      </p>
      <button style={{ padding: 8, marginRight: 8 }} onClick={addPasskey}>
        Add a passkey
      </button>
      <h3>Authenticator app (fallback)</h3>
      {!qr ? (
        <button style={{ padding: 8 }} onClick={startTotp}>Enroll TOTP</button>
      ) : (
        <form onSubmit={confirmTotp} style={{ display: "grid", gap: 8 }}>
          <img
            alt="TOTP QR"
            width="180"
            height="180"
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(qr.qr_svg || "")}`}
          />
          <input style={box} aria-label="6-digit code" placeholder="6-digit code"
            value={code} onChange={(e) => setCode(e.target.value)} />
          <button style={{ padding: 8 }}>Confirm TOTP</button>
        </form>
      )}
      {recovery && (
        <pre style={{ ...box, lineHeight: 1.8 }}>{recovery.join("\n")}</pre>
      )}
      {error && <div style={{ color: "var(--hud-danger)" }}>{error}</div>}
    </div>
  );
}

export default function Settings({ user, events }) {
  const [tab, setTab] = useState("security");
  return (
    <div style={{ padding: 16 }}>
      <nav style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        {SETTINGS_TABS.map((t) => (
          <button key={t.id} style={{ ...box, opacity: tab === t.id ? 1 : 0.6 }}
            onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </nav>
      {tab === "security" && <SecurityPanel user={user} />}
      {tab === "cloudflare" && <CloudflarePanel />}
      {tab === "aws" && <AwsPanel systemAdmin={Boolean(user?.is_system_admin)} />}
      {tab === "partners" && <PartnersPanel systemAdmin={Boolean(user?.is_system_admin)} />}
      {tab === "developer" && <DemoPanel user={user} events={events} />}
      {tab === "vault" && (
        <p style={{ color: "var(--hud-muted)" }}>Vault management gets its screen in Phase 4;
            until then secrets stay CLI-managed and this tab says so.</p>
      )}
    </div>
  );
}

// §4.5 client half: the generated zod mirror (frontend/src/api/zod.ts) validates
// before the wire; the DRF serializer stays the source of truth. Friendly copy for
// zod's generic messages lives here — the rules themselves are never hand-written.
const demoJobErrorMap = (issue, ctx) => {
  if (issue.path[0] === "name") {
    return { message: "Lowercase letters, digits and dashes; start with a letter." };
  }
  if (issue.path[0] === "delay") {
    return { message: "Delay must be between 0.05 and 5.0 seconds." };
  }
  return { message: ctx.defaultError };
};

function snapshotFailedLine(status) {
  if (status === 403) return "⚠ snapshot refused — session expired? Log in again.";
  return "⚠ snapshot refetch failed — will retry on next reconnect.";
}

export function DemoPanel({ user, events }) {
  const { status, subscribe, unsubscribe } = events;
  const [lines, setLines] = useState([]);
  // The pane shows one mode at a time; switching modes unsubscribes the previous
  // topics so stale streams can't interleave and snapshots can't clobber the
  // other mode's lines (round-3 finding). A ref, not state: an async launch
  // resolving after a mode switch must swap the ACTUAL current topics, not a
  // click-time closure (round-4 finding).
  const paneTopicsRef = useRef([]);
  function takePane(topics) {
    paneTopicsRef.current.forEach((t) => unsubscribe(t));
    paneTopicsRef.current = topics;
  }
  const [warnings, setWarnings] = useState(null);
  const [busy, setBusy] = useState(false); // covers the 409-confirm relaunch too
  // §F5: demo.launch is T2, so the click lands in a confirm carrying the summary of
  // what will run — table-driven, so demoting the row demotes the dialog with it.
  const [pending, setPending] = useState(null);
  const {
    register,
    handleSubmit,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(schemas.DemoJob, { errorMap: demoJobErrorMap }),
    defaultValues: { name: "demo", delay: 0.5, confirm_warnings: false },
  });

  // Snapshot-then-stream (§D7): same fetch on first load and on every reconnect.
  // Non-OK snapshot responses carry their status into the failure line.
  const snapshotFn = async (topic) => {
    const { status: st, data } = await api(`topics/${topic}/snapshot/`);
    // Shape-validate: a 200 with an unparseable/foreign body must count as a
    // failed snapshot, not crash the repaint (live-demo finding).
    if (st !== 200 || !Array.isArray(data.data)) throw { status: st };
    return data;
  };

  async function launch(values, confirm = false) {
    if (busy) return;
    setBusy(true);
    setWarnings(null);
    clearErrors();
    const { status: st, data } = await api("demo-jobs/", {
      ...values, confirm_warnings: confirm,
    });
    setBusy(false);
    if (st === 400) {
      // Server verdict wins (§4.5): map {field: [{code, message, hint}]} into RHF.
      for (const [field, errs] of Object.entries(data.errors ?? {})) {
        const e = errs[0];
        setError(field, { type: e.code, message: [e.message, e.hint].filter(Boolean).join(" ") });
      }
    } else if (st === 409 && (data.warnings ?? []).length) {
      setWarnings({ values, body: data.warnings });
    } else if (st !== 201) {
      // Non-contract statuses (0 network, 403 CSRF/session, 500…) never go silent.
      setError("root", { type: String(st), message: data.detail ?? `Unexpected ${st} response.` });
    } else {
      takePane([data.topic]);
      const seed = `— launching ${values.name}… waiting for first log line —`;
      setLines([seed]);
      subscribe(
        data.topic,
        (event) => {
          if (event.__snapshot) {
            // §D7 repaint: snapshot data is the capped history [{seq, event}] — a
            // socket killed mid-stream recovers every line published while dead.
            // An EMPTY first snapshot must keep the seed line, not blank the pane
            // (round-5 finding: the happy path regressed the pending-feedback fix).
            return setLines(
              event.data.length ? event.data.map((e) => e.event.line ?? "✔ done") : [seed]
            );
          }
          if (event.__snapshot_failed)
            return setLines((p) => [...p, snapshotFailedLine(event.status)]);
          setLines((p) => [...p, event.line ?? "✔ done"]);
        },
        snapshotFn
      );
    }
  }

  function submit(values) {
    if (presentation(tierFor("demo.launch")).confirm) setPending(values);
    else launch(values, false);
  }

  // §F8 v0: watch the simulation replayer (manage.py replay_simulation) through the
  // same multiplexed socket — two topics, one panel, real publish() path.
  function watchSimulation() {
    takePane(["demo.sim.log", "findings"]);
    setLines(["— watching simulation topics (run: manage.py replay_simulation) —"]);
    const synced = new Set(); // first snapshot per topic = initial load, not a resync
    const simHandler = (topic, render) => (event) => {
      if (event.__snapshot) {
        const isResync = synced.has(topic);
        synced.add(topic);
        // Append a delimited per-topic block — never replace the shared pane
        // (round-2 finding: one topic's snapshot wiped the other's lines).
        const block = event.data.map((e) => render(e.event));
        if (isResync) return setLines((p) => [...p, `— ${topic} resynced —`, ...block]);
        if (block.length) return setLines((p) => [...p, ...block]);
        return;
      }
      if (event.__snapshot_failed)
        return setLines((p) => [...p, snapshotFailedLine(event.status)]);
      setLines((p) => [...p, render(event)]);
    };
    subscribe("demo.sim.log",
      simHandler("demo.sim.log", (e) => e.line ?? JSON.stringify(e)), snapshotFn);
    subscribe("findings",
      simHandler("findings", (e) => `⚠ ${e.kind} ${e.title ?? e.site ?? ""} ${e.state ?? ""}`), snapshotFn);
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto" }}>
      <h2>
        Demo job{" "}
        <small style={{ color: status === "live" ? "var(--hud-success)" : "var(--hud-warning)" }}>({status})</small>
      </h2>
      <p>Signed in as {user.username}.</p>
      {status === "auth-required" && (
        <div style={{ color: "var(--hud-danger)" }}>
          Session expired or enrollment required — reload and log in again.
        </div>
      )}
      <form onSubmit={handleSubmit(submit)}
        style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
        <label style={{ display: "grid", gap: 4 }}>
          <small>job name</small>
          <input {...register("name")} style={box} placeholder="demo"
            aria-invalid={!!errors.name} />
        </label>
        <label style={{ display: "grid", gap: 4 }}>
          <small>delay (s)</small>
          <input {...register("delay", { valueAsNumber: true })} type="number" step="0.05"
            style={{ ...box, width: 80 }} aria-invalid={!!errors.delay} />
        </label>
        <button style={{ padding: 8 }} disabled={isSubmitting || busy}>
          {isSubmitting || busy ? "Launching…" : "Launch"}
        </button>
        <button type="button" onClick={watchSimulation} style={{ padding: 8 }}>
          Watch simulation
        </button>
      </form>
      {pending && (
        <ConfirmDialog label={tierFor("demo.launch").label}
          summary={`Run "${pending.name}" with a ${pending.delay} s delay between lines.`}
          onConfirm={() => { const v = pending; setPending(null); launch(v, false); }}
          onDismiss={() => setPending(null)} />
      )}
      {Object.entries(errors).map(([field, e]) => (
        <div key={field} style={{ color: "var(--hud-danger)", marginTop: 8 }}>
          {field === "root" ? "" : `${field}: `}{e.message}
        </div>
      ))}
      {warnings && (
        <div style={{ color: "var(--hud-warning)", marginTop: 8 }}>
          {warnings.body.map((w) => <div key={w.code}>⚠ {w.message} {w.hint}</div>)}
          <button onClick={() => launch(warnings.values, true)} style={{ marginTop: 8 }}
            disabled={busy}>
            {busy ? "Launching…" : "I understand, continue"}
          </button>
        </div>
      )}
      <pre style={{ background: "#161a21", padding: 12, minHeight: 220, marginTop: 16 }}>
        {lines.join("\n")}
      </pre>
    </div>
  );
}
