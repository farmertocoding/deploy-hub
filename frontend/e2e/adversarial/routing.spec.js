import { test, expect } from "@playwright/test";
import { openHud, openOperator } from "../helpers.js";

test("hostile finding hash does not execute script", async ({ page }) => {
  const dialogs = [];
  page.on("dialog", (d) => dialogs.push(d.message()));
  await openOperator(page, { hash: "#/findings/<img src=x onerror=alert(1)>" });
  // Sim findingsFixture only matches /v1/findings/<digits>/; a hostile id 404s
  // with empty detail, so Findings paints ErrorLine — not "was not found".
  await expect(page.getByText(/Could not load findings \(HTTP 404\)/i)).toBeVisible();
  expect(dialogs).toEqual([]);
  await expect(page.locator("img[src='x']")).toHaveCount(0);
});

test("javascript hash does not execute and lands Home", async ({ page }) => {
  const dialogs = [];
  page.on("dialog", (d) => dialogs.push(d.message()));
  await openOperator(page, { hash: "#/javascript:alert(1)" });
  await expect(page.getByRole("button", { name: /takko/i })).toBeVisible();
  expect(dialogs).toEqual([]);
});

test("admin not-found site does not render HTML from the id", async ({ page }) => {
  await openHud(page, { hash: "#/admin/sites/<img src=x onerror=alert(1)>" });
  await expect(page.locator("img[src='x']")).toHaveCount(0);
});
