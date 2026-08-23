import { z } from "zod";

const Login = z
  .object({
    username: z.string(),
    password: z.string(),
    otp_code: z.string().optional(),
    webauthn: z.unknown().optional(),
  })
  .passthrough();
const Me = z
  .object({
    authenticated: z.boolean(),
    username: z.string().optional(),
    otp_enrolled: z.boolean().optional(),
    webauthn_count: z.number().int().optional(),
    totp_enrolled: z.boolean().optional(),
    t1_available: z.boolean().optional(),
  })
  .passthrough();
const Confirm = z
  .object({ otp_code: z.string().regex(/^\d{6}$/) })
  .passthrough();
const WebAuthnLoginBegin = z.object({ username: z.string() }).passthrough();
const DemoJob = z
  .object({
    name: z.string().regex(/^[a-z][a-z0-9-]{1,30}$/),
    delay: z.number().gte(0.05).lte(5).optional().default(0.5),
    confirm_warnings: z.boolean().optional().default(false),
  })
  .passthrough();
const CloudflareConnect = z.object({ token: z.string().min(1) }).passthrough();
const ProviderEnum = z.literal("cloudflare");
const DnsAccountConnected = z
  .object({
    id: z.number().int(),
    provider: ProviderEnum.optional(),
    label: z.string().max(128),
  })
  .passthrough();
const PurposeEnum = z.enum(["prod", "test"]);
const DnsZoneConnected = z
  .object({
    id: z.number().int(),
    name: z.string().max(253),
    provider_zone_id: z.string().max(64).optional(),
    purpose: PurposeEnum.optional(),
  })
  .passthrough();
const CloudflareConnectResult = z
  .object({ account: DnsAccountConnected, zone: DnsZoneConnected })
  .passthrough();
const OriginCaPlant = z.object({ path: z.string().min(1) }).passthrough();
const OriginCaPlantResult = z.object({ planted: z.boolean() }).passthrough();
const SeverityEnum = z.enum(["p1", "p2", "p3"]);
const StateEnum = z.enum(["open", "acked", "resolved", "accepted"]);
const Finding = z
  .object({
    id: z.number().int(),
    source_engine: z.string().max(64),
    severity: SeverityEnum,
    entity: z.string().max(128),
    title: z.string().max(256),
    body: z.string().optional(),
    fix_action: z.string().max(256).optional(),
    state: StateEnum.optional(),
    first_seen: z.string().datetime({ offset: true }).optional(),
    last_seen: z.string().datetime({ offset: true }).optional(),
    fingerprint: z.string().max(128),
    accepted_reason: z.string().max(256).optional(),
  })
  .passthrough();
const FindingListSnapshot = z
  .object({ seq: z.number().int(), data: z.array(Finding) })
  .passthrough();
const FindingDetailSnapshot = z
  .object({ seq: z.number().int(), data: Finding })
  .passthrough();
const ActionEnum = z.enum(["ack", "resolve", "accept_risk"]);
const Transition = z
  .object({
    action: ActionEnum,
    reason: z.string().max(256).optional().default(""),
  })
  .passthrough();
const IdEnum = z.enum([
  "enroll_target",
  "connect_cloudflare",
  "plant_origin_ca",
  "add_project",
]);
const FirstRunItem = z
  .object({ id: IdEnum, applicable: z.boolean(), done: z.boolean() })
  .passthrough();
const FirstRunProgress = z
  .object({ owns_home: z.boolean(), items: z.array(FirstRunItem) })
  .passthrough();
const FirstRunSnapshot = z
  .object({ seq: z.number().int(), data: FirstRunProgress })
  .passthrough();
const KindEnum = z.enum(["zone", "host", "container", "hub", "edge"]);
const MapNode = z
  .object({
    id: z.string(),
    kind: KindEnum,
    label: z.string(),
    status: z.string(),
    parent: z.string().optional(),
  })
  .passthrough();
const PathEnum = z.enum(["public", "mesh"]);
const MapEdge = z
  .object({ a: z.string(), b: z.string(), path: PathEnum })
  .passthrough();
const MapGraph = z
  .object({ nodes: z.array(MapNode), edges: z.array(MapEdge) })
  .passthrough();
const MapSnapshot = z
  .object({ seq: z.number().int(), data: MapGraph })
  .passthrough();
const CertRefusal = z
  .object({ detail: z.string(), finding_id: z.number().int() })
  .passthrough();
const AttackState = z
  .object({
    detail: z.string(),
    finding_id: z.number().int(),
    mode: z.string(),
  })
  .passthrough();
const EdgeOwnerEnum = z.enum(["host_caddy", "site_caddy"]);
const SiteSummary = z
  .object({
    id: z.number().int(),
    name: z.string(),
    domain: z.string(),
    latest_manifest_version: z.number().int().nullable(),
    manifest_current: z.boolean().nullable(),
    cert_refusal: CertRefusal.nullish(),
    attack_state: AttackState.nullish(),
    edge_owner: EdgeOwnerEnum.optional(),
  })
  .passthrough();
const ProjectSummary = z
  .object({
    id: z.number().int(),
    name: z.string(),
    slug: z.string(),
    scanned_at: z.string().datetime({ offset: true }).nullable(),
    tiers: z.record(z.number().int()),
    sites: z.array(SiteSummary),
  })
  .passthrough();
const ExposureEnum = z.enum(["public", "mesh_only"]);
const ProjectCreate = z
  .object({
    name: z.string().max(128),
    git_url: z.string().optional().default(""),
    git_ref: z.string().optional().default("main"),
    local_path: z.string().optional().default(""),
    domain: z.string().optional().default(""),
    exposure: ExposureEnum.optional().default("public"),
    proxied: z.boolean().optional().default(true),
    dns_zone: z.number().int().nullish(),
    primary_target: z.number().int().nullish(),
  })
  .passthrough();
const Readiness = z
  .object({
    scanned_at: z.string().datetime({ offset: true }).nullable(),
    modules: z.array(z.string()),
    summary: z.object({}).partial().passthrough(),
    blockers: z.array(z.object({}).partial().passthrough()),
    warnings: z.array(z.object({}).partial().passthrough()),
    advice: z.array(z.object({}).partial().passthrough()),
    pending_sandbox: z.array(z.object({}).partial().passthrough()),
  })
  .passthrough();
const PatchedSiteEdgeOwner = z
  .object({ edge_owner: EdgeOwnerEnum })
  .partial()
  .passthrough();
const SiteEdgeOwner = z.object({ edge_owner: EdgeOwnerEnum }).passthrough();
const BackupDump = z
  .object({
    id: z.number().int(),
    bytes: z.number().int(),
    digest: z.string(),
    stored_at: z.string(),
    status: z.string(),
  })
  .passthrough();
const BackupUnit = z
  .object({
    id: z.number().int(),
    kind: z.string(),
    schedule: z.string(),
    dumps: z.array(BackupDump),
  })
  .passthrough();
const BackupList = z
  .object({ units: z.array(BackupUnit), restore_command: z.string() })
  .passthrough();
const BackupRun = z
  .object({
    schema_version: z.number().int(),
    unit_id: z.number().int(),
    site_id: z.number().int(),
    bytes: z.number().int(),
    digest: z.string(),
    stored_at: z.string(),
  })
  .passthrough();
const EnvNames = z
  .object({ names: z.array(z.string()), config_stale: z.boolean() })
  .passthrough();
const EnvApply = z.object({ deployment_id: z.number().int() }).passthrough();
const EnvWrite = z.object({ env: z.record(z.string()) }).passthrough();
const PatchedEnvWrite = z
  .object({ env: z.record(z.string()) })
  .partial()
  .passthrough();
const Manifest = z
  .object({
    version: z.number().int(),
    schema_version: z.number().int(),
    body: z.unknown(),
    scan_report_hash: z.string(),
    created_at: z.string().datetime({ offset: true }),
  })
  .passthrough();
const Materialize = z
  .object({ confirm_warnings: z.boolean().default(false) })
  .partial()
  .passthrough();
const RollbackResult = z
  .object({
    deployment_id: z.number().int(),
    original_id: z.number().int(),
    status: z.string(),
  })
  .passthrough();
const Question = z
  .object({
    id: z.string(),
    prompt: z.string(),
    kind: z.string(),
    default: z.unknown().nullish(),
    choices: z.array(z.string()).optional(),
    secret: z.boolean(),
  })
  .passthrough();
const WizardState = z
  .object({
    questions: z.array(Question),
    answered: z.object({}).partial().passthrough(),
    blocking: z.array(z.object({}).partial().passthrough()),
    warnings: z.array(z.object({}).partial().passthrough()),
    can_materialize: z.boolean(),
  })
  .passthrough();
const PatchedAnswers = z
  .object({ answers: z.object({}).partial().passthrough() })
  .passthrough();
const TargetDelete = z.object({ confirm_name: z.string() }).passthrough();
const SshRotate = z.object({ confirm_name: z.string() }).passthrough();

export const schemas = {
  Login,
  Me,
  Confirm,
  WebAuthnLoginBegin,
  DemoJob,
  CloudflareConnect,
  ProviderEnum,
  DnsAccountConnected,
  PurposeEnum,
  DnsZoneConnected,
  CloudflareConnectResult,
  OriginCaPlant,
  OriginCaPlantResult,
  SeverityEnum,
  StateEnum,
  Finding,
  FindingListSnapshot,
  FindingDetailSnapshot,
  ActionEnum,
  Transition,
  IdEnum,
  FirstRunItem,
  FirstRunProgress,
  FirstRunSnapshot,
  KindEnum,
  MapNode,
  PathEnum,
  MapEdge,
  MapGraph,
  MapSnapshot,
  CertRefusal,
  AttackState,
  EdgeOwnerEnum,
  SiteSummary,
  ProjectSummary,
  ExposureEnum,
  ProjectCreate,
  Readiness,
  PatchedSiteEdgeOwner,
  SiteEdgeOwner,
  BackupDump,
  BackupUnit,
  BackupList,
  BackupRun,
  EnvNames,
  EnvApply,
  EnvWrite,
  PatchedEnvWrite,
  Manifest,
  Materialize,
  RollbackResult,
  Question,
  WizardState,
  PatchedAnswers,
  TargetDelete,
  SshRotate,
};
