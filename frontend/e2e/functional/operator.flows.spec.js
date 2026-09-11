import { test, expect } from "@playwright/test";
import { openOperator } from "../helpers.js";

test("takko prod materialize creates manifest v4", async ({ page }) => {
  await openOperator(page, { hash: "#/" });
  await page.getByRole("button", { name: /takko/i }).click();
  await page.getByRole("button", { name: /Configure & materialize — prod/i }).click();
  await page.getByRole("button", { name: /Materialize manifest/i }).click();
  await expect(page.getByText(/Manifest v4 created/i)).toBeVisible();
});

test("takko staging save domain then materialize creates manifest v1", async ({ page }) => {
  await openOperator(page, { hash: "#/" });
  await page.getByRole("button", { name: /takko/i }).click();
  await page.getByRole("button", { name: /Configure & materialize — staging/i }).click();
  const domain = page.getByLabel(/Public domain for this site/i);
  await domain.fill("staging.takko.market");
  await page.getByRole("button", { name: /Save answers/i }).click();
  await expect(page.getByText(/Saved/i)).toBeVisible();
  await page.getByRole("button", { name: /Materialize manifest/i }).click();
  await expect(page.getByText(/Manifest v1 created/i)).toBeVisible();
});

test("atlas-edge materialize without warning ack is refused", async ({ page }) => {
  await openOperator(page, { hash: "#/" });
  await page.getByRole("button", { name: /atlas-edge/i }).click();
  await page.getByRole("button", { name: /Configure & materialize — prod/i }).click();
  await page.getByRole("button", { name: /Materialize manifest/i }).click();
  await expect(page.getByText(/Materialization refused/i)).toBeVisible();
  await expect(page.getByText(/warnings_unconfirmed/i)).toBeVisible();
  await expect(page.getByText(/Manifest v1 created/i)).toHaveCount(0);
});

test("atlas-edge materialize after ack creates manifest v1", async ({ page }) => {
  await openOperator(page, { hash: "#/" });
  await page.getByRole("button", { name: /atlas-edge/i }).click();
  await page.getByRole("button", { name: /Configure & materialize — prod/i }).click();
  await page.getByRole("checkbox", { name: /I have read these 2 warnings/i }).check();
  await page.getByRole("button", { name: /Materialize manifest/i }).click();
  await expect(page.getByText(/Manifest v1 created/i)).toBeVisible();
});

test("Cloudflare settings shows path-only Origin-CA plant", async ({ page }) => {
  await openOperator(page, { hash: "#/settings" });
  await page.getByRole("button", { name: "Cloudflare" }).click();
  await expect(page.getByRole("heading", { name: "Origin-CA plant" })).toBeVisible();
  await expect(page.getByText(/does not accept a paste/i)).toBeVisible();
  await expect(page.getByText(/v1\.0- service key/i)).toBeVisible();
  await expect(page.getByLabel("Origin-CA DNS account")).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(1);
  await expect(page.getByRole("button", { name: /Plant Origin CA/i })).toBeVisible();
  await expect(page.locator("form").filter({ hasText: "path" }).locator('input[type="text"]')).toBeVisible();
});
