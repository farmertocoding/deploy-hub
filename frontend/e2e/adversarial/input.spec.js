import { test, expect } from "@playwright/test";
import { openOperator } from "../helpers.js";

test("Origin-CA plant with empty path does not POST token bytes", async ({ page }) => {
  const posts = [];
  page.on("request", (req) => {
    if (req.method() === "POST") posts.push({ url: req.url(), body: req.postData() || "" });
  });
  await openOperator(page, { hash: "#/settings" });
  await page.getByRole("button", { name: "Cloudflare" }).click();
  await page.getByRole("button", { name: /^Plant$/i }).click();
  const plantPosts = posts.filter((p) => p.url.includes("origin-ca-plant"));
  expect(plantPosts).toEqual([]);
});

test("Vite without sim shows unreachable, not logged-out", async ({ page }) => {
  // No prepareHud, no ?sim=. Abort Django /api so fetch throws (status 0).
  // pathname pin: **/api/** would also kill Vite modules under /src/api/.
  await page.route((url) => url.pathname.startsWith("/api/"), (route) => route.abort());
  await page.goto("/#/admin");
  await expect(page.getByText(/Cannot reach server/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Retry/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Deploy Hub" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Fleet overview/i })).toHaveCount(0);
});
