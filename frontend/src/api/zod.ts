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

export const schemas = {
  Login,
  Confirm,
  DemoJob,
};
