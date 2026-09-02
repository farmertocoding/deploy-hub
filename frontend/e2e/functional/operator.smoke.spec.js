import { test, expect } from "@playwright/test";
import { openOperator, OPERATOR_NAV } from "../helpers.js";

test("operator sidenav lists the six NAV items and not Administration", async ({ page }) => {
  await openOperator(page, { hash: "#/" });
  const nav = page.getByRole("navigation", { name: /Operator/i });
  for (const label of OPERATOR_NAV) {
    await expect(nav.getByRole("button", { name: label })).toBeVisible();
  }
  await expect(nav.getByRole("button", { name: "Administration" })).toHaveCount(0);
});

test("operator Home live shows readiness projects", async ({ page }) => {
  await openOperator(page, { hash: "#/" });
  await expect(page.getByRole("button", { name: /takko/i })).toBeVisible();
});

test("operator first-run checklist owns Home under ?sim=empty", async ({ page }) => {
  await openOperator(page, { sim: "empty", hash: "#/" });
  await expect(page.getByRole("button", { name: /Copy the provision command/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Connect Cloudflare/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Add a project/i })).toBeVisible();
});

test("unknown operator hash lands on Home", async ({ page }) => {
  await openOperator(page, { hash: "#/nope" });
  await expect(page.getByRole("button", { name: /takko/i })).toBeVisible();
});
