import { test, expect } from "@playwright/test";
import { openHud, waitAdminReady } from "../helpers.js";

test("add application wizard walks Source to Review", async ({ page }) => {
  await openHud(page, { hash: "#/admin/projects/new" });
  await expect(page.getByRole("heading", { name: /Add application/i })).toBeVisible();
  await page.getByLabel(/Project name/i).fill("canary");
  await page.getByLabel(/Git URL|Local path/i).first().fill("https://example.test/canary.git");
  await page.getByRole("button", { name: /Test source/i }).click();
  await expect(page.getByText(/Connection status: connected/i)).toBeVisible();
  await page.getByRole("button", { name: /^Continue$/i }).click();
  await expect(page.getByLabel(/Site name/i)).toBeVisible();
});

test("live deployment abort confirm queues operation 42", async ({ page }) => {
  await openHud(page, { hash: "#/admin/deployments/11" });
  await waitAdminReady(page, "Live deployment");
  await page.getByRole("button", { name: /Abort and clean up/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /Confirm — Abort and clean up/i }).click();
  await expect(page.getByText(/accepted operation 42/i)).toBeVisible();
});

test("create target opens T1 overlay", async ({ page }) => {
  await openHud(page, { hash: "#/admin/targets" });
  await waitAdminReady(page, "Targets");
  await page.getByRole("button", { name: /Create Target/i }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText(/Type the name and touch a security key/i)).toBeVisible();
});

test("sites table does not offer an enabled Delete", async ({ page }) => {
  await openHud(page, { hash: "#/admin/sites" });
  await waitAdminReady(page, "Sites fleet");
  const more = page.getByText(/^More actions$/i).first();
  await more.click();
  const del = page.getByRole("button", { name: /^Delete$/i });
  if (await del.count()) {
    await expect(del).toHaveAttribute("aria-disabled", "true");
    await del.click({ force: true });
    await expect(page.getByText(/accepted operation 42/i)).toHaveCount(0);
  }
});
