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
const AwsStatus = z
  .object({ connected: z.boolean(), reason: z.string() })
  .passthrough();
const AwsConnect = z
  .object({
    access_key_id: z.string().min(1),
    secret_access_key: z.string().min(1),
    region: z.string().optional().default("us-east-1"),
  })
  .passthrough();
const AwsConnectResult = z
  .object({ account_id_last4: z.string(), region: z.string() })
  .passthrough();
const CloudflareConnect = z.object({ token: z.string().min(1) }).passthrough();
const ProviderEnum = z.enum(["cloudflare", "route53"]);
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
const InstanceCreateCost = z
  .object({ cost: z.number(), cost_display: z.string() })
  .passthrough();
const InstanceCreate = z
  .object({
    confirm_name: z.string(),
    host: z.string(),
    zone: z.string().regex(/^[-a-zA-Z0-9_]+$/),
    instance_type: z.string().optional().default("t3.micro"),
    overflow_site: z.number().int().optional(),
  })
  .passthrough();
const InstanceCreateResult = z
  .object({ id: z.number().int(), host: z.string(), kind: z.string() })
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
const ConfirmName = z.object({ confirm_name: z.string() }).passthrough();
const PartnerDestination = z
  .object({ id: z.number().int(), host: z.string(), kind: z.string() })
  .passthrough();
const PartnerPublic = z
  .object({
    id: z.number().int(),
    slug: z.string(),
    name: z.string(),
    destination_order: z.array(z.number().int()),
    destinations: z.array(PartnerDestination),
    suspended: z.boolean(),
    site_ids: z.array(z.number().int()),
  })
  .passthrough();
const StatusEnum = z.enum(["degraded", "error"]);
const IntakeStatusModeEnum = z.enum(["fake", "configured"]);
const IntakeStatus = z
  .object({
    status: StatusEnum,
    mode: IntakeStatusModeEnum,
    configured: z.boolean(),
    as_of: z.string().nullish(),
  })
  .passthrough();
const CandidateTarget = z
  .object({
    id: z.number().int(),
    host: z.string(),
    kind: z.string(),
    tunnel: z.boolean(),
  })
  .passthrough();
const PartnerList = z
  .object({
    partners: z.array(PartnerPublic),
    intake: IntakeStatus,
    api_enabled: z.boolean(),
    candidate_targets: z.array(CandidateTarget),
  })
  .passthrough();
const PartnerCreate = z
  .object({
    slug: z
      .string()
      .max(64)
      .regex(/^[-a-zA-Z0-9_]+$/),
    name: z.string().max(128).optional().default(""),
    confirm_name: z.string(),
  })
  .passthrough();
const PartnerCreateResult = z
  .object({
    id: z.number().int(),
    slug: z.string(),
    name: z.string(),
    hubk: z.string(),
    whsec: z.string(),
  })
  .passthrough();
const DestinationRank = z
  .object({ destination_order: z.array(z.number().int()) })
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
    scale_ready: z.boolean().optional(),
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
const OverflowDeploy = z
  .object({ target: z.number().int(), confirm_name: z.string() })
  .passthrough();
const OverflowDeployResult = z
  .object({ deployment: z.number().int(), target: z.number().int() })
  .passthrough();
const OverflowJoin = z
  .object({ target: z.number().int(), confirm_name: z.string() })
  .passthrough();
const OverflowJoinResult = z
  .object({
    target: z.number().int(),
    joined: z.string(),
    name: z.string().optional(),
    values: z.array(z.string()).optional(),
  })
  .passthrough();
const OverflowScaleIn = z
  .object({ target: z.number().int(), confirm_name: z.string() })
  .passthrough();
const OverflowScaleInResult = z
  .object({ target: z.number().int(), unjoined: z.string() })
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
const BackupRestore = z
  .object({ checkrun_pk: z.number().int(), confirm_name: z.string() })
  .passthrough();
const BackupRestoreResult = z
  .object({
    ok: z.boolean(),
    unit_id: z.number().int(),
    checkrun_pk: z.number().int(),
  })
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
const TargetList = z
  .object({
    id: z.number().int(),
    host: z.string(),
    kind: z.string(),
    tunnel: z.boolean(),
  })
  .passthrough();
const RouterAdviceModeEnum = z.enum(["tunnel", "not_tunnel", "no_seam"]);
const RouterAdvice = z
  .object({
    mode: RouterAdviceModeEnum,
    forwarded: z.boolean(),
    finding_id: z.number().int().nullable(),
    title: z.string(),
    body: z.string(),
  })
  .passthrough();
const TargetDetail = z
  .object({
    id: z.number().int(),
    host: z.string(),
    kind: z.string(),
    tunnel: z.boolean(),
    router_advice: RouterAdvice,
  })
  .passthrough();
const TargetDelete = z.object({ confirm_name: z.string() }).passthrough();
const RouterProbeResult = z
  .object({
    ok: z.boolean(),
    target_id: z.number().int(),
    forwarded: z.boolean(),
    finding_id: z.number().int().nullable(),
  })
  .passthrough();
const SshRotate = z.object({ confirm_name: z.string() }).passthrough();
const InstanceTerminate = z.object({ confirm_name: z.string() }).passthrough();

export const schemas = {
  Login,
  Me,
  Confirm,
  WebAuthnLoginBegin,
  DemoJob,
  AwsStatus,
  AwsConnect,
  AwsConnectResult,
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
  InstanceCreateCost,
  InstanceCreate,
  InstanceCreateResult,
  KindEnum,
  MapNode,
  PathEnum,
  MapEdge,
  MapGraph,
  MapSnapshot,
  ConfirmName,
  PartnerDestination,
  PartnerPublic,
  StatusEnum,
  IntakeStatusModeEnum,
  IntakeStatus,
  CandidateTarget,
  PartnerList,
  PartnerCreate,
  PartnerCreateResult,
  DestinationRank,
  CertRefusal,
  AttackState,
  EdgeOwnerEnum,
  SiteSummary,
  ProjectSummary,
  ExposureEnum,
  ProjectCreate,
  Readiness,
  OverflowDeploy,
  OverflowDeployResult,
  OverflowJoin,
  OverflowJoinResult,
  OverflowScaleIn,
  OverflowScaleInResult,
  PatchedSiteEdgeOwner,
  SiteEdgeOwner,
  BackupDump,
  BackupUnit,
  BackupList,
  BackupRestore,
  BackupRestoreResult,
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
  TargetList,
  RouterAdviceModeEnum,
  RouterAdvice,
  TargetDetail,
  TargetDelete,
  RouterProbeResult,
  SshRotate,
  InstanceTerminate,
};
