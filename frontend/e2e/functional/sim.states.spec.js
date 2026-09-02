import { test, expect } from "@playwright/test";
import { openOperator, simUrl } from "../helpers.js";

test("sim=loading keeps the named spinner and invents no rows", async ({ page }) => {
  await openOperator(page, { sim: "loading", hash: "#/" });
  await expect(page.getByText(/Loading home/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /takko/i })).toHaveCount(0);
  await page.waitForTimeout(2000);
  await expect(page.getByRole("button", { name: /takko/i })).toHaveCount(0);
});

test("sim=error shows retry and not a live fleet", async ({ page }) => {
  await openOperator(page, { sim: "error", hash: "#/" });
  await page.getByRole("navigation", { name: /Operator/i }).getByRole("button", { name: "Sites" }).click();
  await expect(page.getByText(/Cannot reach server/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Retry/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /takko/i })).toHaveCount(0);
});

test("sim=stale materialize of takko prod is refused and stays refused", async ({ page }) => {
  await openOperator(page, { sim: "stale", hash: "#/" });
  await page.getByRole("button", { name: /takko/i }).click();
  await page.getByRole("button", { name: /Configure & materialize — prod/i }).click();
  await page.getByRole("button", { name: /Materialize manifest/i }).click();
  await expect(page.getByText(/Materialization refused/i)).toBeVisible();
  await expect(page.getByText("blockers_present")).toBeVisible();
  await expect(page.getByText(/Manifest v4 created/i)).toHaveCount(0);
});

test("unknown sim name does not fetch /api", async ({ page }) => {
  const apiCalls = [];
  page.on("request", (req) => {
    if (new URL(req.url()).pathname.startsWith("/api/")) apiCalls.push(req.url());
  });
  await page.goto(simUrl("not-a-fixture", "#/"));
  await page.waitForTimeout(500);
  expect(apiCalls).toEqual([]);
});

test("sim=degraded Home shows scan-required project", async ({ page }) => {
  await openOperator(page, { sim: "degraded", hash: "#/" });
  await page.getByRole("button", { name: /orders-api/i }).click();
  await expect(page.getByText(/Not scanned yet/i)).toBeVisible();
});
