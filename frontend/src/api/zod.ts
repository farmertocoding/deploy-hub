import { z } from "zod";

const Login = z
  .object({
    username: z.string(),
    password: z.string(),
    otp_code: z.string().optional(),
  })
  .passthrough();
const Confirm = z
  .object({ otp_code: z.string().regex(/^\d{6}$/) })
  .passthrough();
const DemoJob = z
  .object({
    name: z.string().regex(/^[a-z][a-z0-9-]{1,30}$/),
    delay: z.number().gte(0.05).lte(5).optional().default(0.5),
    confirm_warnings: z.boolean().optional().default(false),
  })
  .passthrough();
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
const SiteSummary = z
  .object({
    id: z.number().int(),
    name: z.string(),
    domain: z.string(),
    latest_manifest_version: z.number().int().nullable(),
    manifest_current: z.boolean().nullable(),
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

export const schemas = {
  Login,
  Confirm,
  DemoJob,
  SeverityEnum,
  StateEnum,
  Finding,
  FindingListSnapshot,
  FindingDetailSnapshot,
  ActionEnum,
  Transition,
  SiteSummary,
  ProjectSummary,
  Readiness,
  EnvNames,
  EnvApply,
  EnvWrite,
  PatchedEnvWrite,
  Manifest,
  Materialize,
  Question,
  WizardState,
  PatchedAnswers,
};
