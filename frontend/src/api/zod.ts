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
  .partial()
  .passthrough();

export const schemas = {
  Login,
  Confirm,
  DemoJob,
  SiteSummary,
  ProjectSummary,
  Readiness,
  Manifest,
  Materialize,
  Question,
  WizardState,
  PatchedAnswers,
};
