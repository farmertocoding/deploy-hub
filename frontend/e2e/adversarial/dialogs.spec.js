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
  const confirm = dialog.getByRole("button", { name: /Confirm — Abort and clean up/i });
  await expect(confirm).toBeVisible();
  // Fail closed on ConfirmAction no-busy: first Enter must aria-disabled/aria-busy the
  // Confirm control. Unmounting after the sim POST returns is not a lock.
  await confirm.evaluate((btn) => {
    globalThis.__confirmLocked = new Promise((resolve) => {
      const locked = () =>
        btn.disabled
        || btn.getAttribute("aria-disabled") === "true"
        || btn.getAttribute("aria-busy") === "true";
      const obs = new MutationObserver(() => {
        if (locked()) {
          obs.disconnect();
          resolve(true);
        }
      });
      obs.observe(btn, { attributes: true, attributeFilter: ["disabled", "aria-disabled", "aria-busy"] });
      btn.addEventListener("click", () => {
        requestAnimationFrame(() => {
          if (locked()) {
            obs.disconnect();
            resolve(true);
            return;
          }
          obs.disconnect();
          resolve(false);
        });
      }, { once: true });
    });
  });
  await page.keyboard.press("Enter");
  expect(
    await page.evaluate(() => globalThis.__confirmLocked),
    "ConfirmAction must disable Confirm after the first Enter",
  ).toBe(true);
  for (let i = 0; i < 8; i += 1) await page.keyboard.press("Enter");
  if (await dialog.count()) {
    await expect(confirm).toHaveAttribute("aria-disabled", "true");
  } else {
    await expect(dialog).toHaveCount(0);
  }
  const hits = page.getByText(/accepted operation 42/i);
  await expect(hits).toHaveCount(1);
});
