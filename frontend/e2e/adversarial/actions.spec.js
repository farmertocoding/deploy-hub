import { test, expect } from "@playwright/test";
import { openHud, openOperator, waitAdminReady } from "../helpers.js";

test("operator restore T1 refuses empty and wrong name", async ({ page }) => {
  await openOperator(page, { hash: "#/sites/1" });
  await page.getByRole("button", { name: /Restore into clean container/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /Confirm — Restore/i }).click();
  await expect(page.getByText(/Requires hardware touch|type-the-name/i)).toBeVisible();
});

test("AWS connect is hidden for the default sim user", async ({ page }) => {
  await openOperator(page, { hash: "#/settings" });
  await page.getByRole("button", { name: "AWS" }).click();
  await expect(page.getByText(/system-administrator action/i)).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
});

test("force-click disabled site Delete does not queue HUD command", async ({ page }) => {
  await openHud(page, { hash: "#/admin/sites" });
  await waitAdminReady(page, "Sites fleet");
  await page.getByText(/^More actions$/i).first().click();
  const del = page.getByRole("button", { name: /^Delete$/i });
  await expect(del).toHaveAttribute("aria-disabled", "true");
  await del.click({ force: true });
  await expect(page.getByText(/accepted operation 42/i)).toHaveCount(0);
});
