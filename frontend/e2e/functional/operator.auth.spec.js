import { test, expect } from "@playwright/test";
import { openAuth, simUrl } from "../helpers.js";

test("login surface has passkey and TOTP toggle", async ({ page }) => {
  await openAuth(page, "login");
  await expect(page.getByRole("heading", { name: "Deploy Hub" })).toBeVisible();
  await expect(page.getByLabel("username")).toBeVisible();
  await expect(page.getByLabel("password")).toBeVisible();
  await expect(page.getByRole("button", { name: /Sign in with passkey/i })).toBeVisible();
  await page.getByRole("button", { name: /Use authenticator code instead/i }).click();
  await expect(page.getByLabel(/TOTP or recovery code/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Log in/i })).toBeVisible();
});

test("login sim ignores admin deep link", async ({ page }) => {
  await page.goto(simUrl("login", "#/admin/overview"));
  await expect(page.getByRole("heading", { name: "Deploy Hub" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Fleet overview/i })).toHaveCount(0);
});

test("enroll shows recovery-codes-once path", async ({ page }) => {
  await openAuth(page, "enroll");
  await page.getByRole("button", { name: /Register a security key/i }).click();
  await expect(page.getByRole("heading", { name: /Recovery codes — shown once/i })).toBeVisible();
});

test("isolated T1 overlay is labeled Delete target", async ({ page }) => {
  await openAuth(page, "t1");
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText(/Type the name and touch a security key/i)).toBeVisible();
});
