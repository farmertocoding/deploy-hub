// §4.5 client-half contract tests: the GENERATED zod mirror must enforce the same
// rules the DRF serializer declares. Run: make test-frontend (node --import tsx --test).
// If these fail after `make generate-client`, the serializer and the mirror drifted —
// which is exactly what the pipeline exists to make impossible to miss.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { schemas } from "../src/api/zod.ts";

test("DemoJob: serializer name rule mirrored (regex)", () => {
  assert.equal(schemas.DemoJob.safeParse({ name: "demo" }).success, true);
  for (const bad of ["BAD NAME", "1starts-with-digit", "x", "a".repeat(40), ""]) {
    assert.equal(schemas.DemoJob.safeParse({ name: bad }).success, false, `should reject: ${bad}`);
  }
});

test("DemoJob: delay bounds mirrored (0.05–5.0) and default applied", () => {
  assert.equal(schemas.DemoJob.safeParse({ name: "demo", delay: 0.04 }).success, false);
  assert.equal(schemas.DemoJob.safeParse({ name: "demo", delay: 5.1 }).success, false);
  const parsed = schemas.DemoJob.parse({ name: "demo" });
  assert.equal(parsed.delay, 0.5);
  assert.equal(parsed.confirm_warnings, false);
});

test("Confirm: TOTP code shape mirrored (6 digits)", () => {
  assert.equal(schemas.Confirm.safeParse({ otp_code: "123456" }).success, true);
  assert.equal(schemas.Confirm.safeParse({ otp_code: "12345" }).success, false);
  assert.equal(schemas.Confirm.safeParse({ otp_code: "abcdef" }).success, false);
});

test("zod.ts is schemas-only (no zodios client import — D-002)", () => {
  const src = readFileSync(fileURLToPath(new URL("../src/api/zod.ts", import.meta.url)), "utf8");
  assert.ok(!src.includes("@zodios/core"), "generated file must not depend on @zodios/core");
});
