import { test, expect } from "@playwright/test";
import { openHud, waitAdminReady } from "../helpers.js";

test("abort dialog Escape and backdrop do not queue an operation", async ({ page }) => {
  await openHud(page, { hash: "#/admin/deployments/11" });
  await waitAdminReady(page, "Live deployment");
  await page.getByRole("button", { name: /Abort and clean up/i }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText(/accepted operation 42/i)).toHaveCount(0);
});

test("abort dialog Enter-spam does not enqueue a second operation", async ({ page }) => {
  await openHud(page, { hash: "#/admin/deployments/11" });
  await waitAdminReady(page, "Live deployment");
  await page.getByRole("button", { name: /Abort and clean up/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  for (let i = 0; i < 8; i += 1) await page.keyboard.press("Enter");
  const hits = page.getByText(/accepted operation 42/i);
  await expect(hits).toHaveCount(1);
});
