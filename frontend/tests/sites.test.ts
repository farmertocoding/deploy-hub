// Sites-screen state + live T3 actions (phase-exit I2 / I4).
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };
(globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

import { AttackBanner } from "../src/screens/Home.jsx";
import {
  AttackState, BackupPanel, CertState, SiteStatus, SitesView, flattenSites,
  restoreBackup, rollbackSite, t3SiteActions, testBackupNow,
} from "../src/screens/Sites.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

const SITE = {
  id: 4,
  name: "bare",
  domain: "bare.example.test",
  project: "refuse-me",
  latest_manifest_version: 1,
  manifest_current: true,
  cert_refusal: {
    detail: "bare.example.test is public with proxied=false.",
    finding_id: 9,
  },
};

test("attack_state_is_visible_site_state", () => {
  const site = {
    ...SITE,
    attack_state: {
      detail: "Under-Attack mode flipped; banned 203.0.113.9.",
      finding_id: 11,
      mode: "under_attack",
    },
  };
  const markup = render(AttackState, { site });
  const text = visibleText(markup);
  assert.match(text, /Under attack/i);
  assert.ok(text.includes(site.attack_state.detail), text);
  assert.match(markup, /href="#\/findings\/11"/);
});

test("home_attack_banner_links_hash_findings", () => {
  const markup = render(AttackBanner, {
    findings: [{
      id: 11,
      fingerprint: "attack-playbook-engaged:3",
      state: "open",
      title: "Attack playbook engaged",
    }],
  });
  const text = visibleText(markup);
  assert.match(text, /Under attack/i);
  assert.match(markup, /href="#\/findings\/11"/);
});

test("attack_state_notify_only_is_degraded_not_silent", () => {
  const site = {
    ...SITE,
    attack_state: {
      detail: "notify-only: no edge token, Under-Attack was not set.",
      finding_id: 12,
      mode: "notify_only",
    },
  };
  const markup = render(AttackState, { site });
  const text = visibleText(markup);
  assert.match(text, /notify-only|degraded/i);
  assert.match(markup, /href="#\/findings\/12"/);
});

test("cert_refusal_is_visible_site_state", () => {
  const markup = render(CertState, { site: SITE });
  const text = visibleText(markup);
  assert.match(text, /TLS refused/);
  assert.ok(text.includes(SITE.cert_refusal.detail), text);
  assert.match(markup, /href="#\/findings\/9"/);
});

test("live_site_status_renders_t3_actions_including_rollback", () => {
  const ids = t3SiteActions();
  assert.deepEqual(ids, ["site.rollback", "site.restart", "check.rerun"]);
  const markup = render(SiteStatus, { site: SITE, actions: ids });
  const text = visibleText(markup);
  assert.match(text, /Roll back/);
  assert.match(text, /Restart/);
  assert.match(text, /Re-run check/);
  assert.doesNotMatch(markup, /role="dialog"/);
});

test("sites_view_passes_t3_ids_into_the_selected_status", () => {
  const markup = render(SitesView, {
    phase: "live", sites: [SITE], selectedId: 4,
    onSelect: () => {}, onNav: () => {},
  });
  const text = visibleText(markup);
  assert.match(text, /TLS refused/);
  assert.match(text, /Roll back/);
});

test("rollback_site_posts_the_smallest_http", async () => {
  const calls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: opts?.body ? JSON.parse(opts.body) : undefined });
    return { status: 201, json: async () => ({ deployment_id: 2, original_id: 1 }) };
  };
  const { status } = await rollbackSite(4);
  assert.equal(status, 201);
  assert.equal(calls[0].url, "/api/v1/sites/4/rollback/");
});

test("app_and_sites_source_wire_the_live_path", () => {
  const sites = readFileSync(new URL("../src/screens/Sites.jsx", import.meta.url), "utf8");
  assert.match(sites, /t3SiteActions/);
  assert.match(sites, /site\.rollback/);
  assert.match(sites, /<SiteStatus/);
  const flatten = flattenSites([{ name: "p", sites: [{ id: 1, name: "s" }] }]);
  assert.equal(flatten[0].project, "p");
});

const BACKUPS = {
  units: [{
    id: 1,
    kind: "postgres",
    schedule: "0 2 * * *",
    dumps: [{
      id: 9,
      bytes: 4096,
      digest: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      stored_at: "2026-08-23T02:00:00+00:00",
      status: "succeeded",
    }],
  }],
  restore_command: "age -d -i backup.key /var/lib/deploy-hub/backups/9 | pg_restore --clean",
};

test("restore_is_command_block_not_a_post", () => {
  const markup = render(BackupPanel, { site: SITE, backups: BACKUPS });
  const text = visibleText(markup);
  assert.match(markup, /<pre/);
  assert.match(text, /pg_restore/);
  assert.match(text, /Test backup now/);
  assert.match(text, /Restore into clean container/);
  const src = readFileSync(new URL("../src/screens/Sites.jsx", import.meta.url), "utf8");
  assert.match(src, /export function AttackState/);
  assert.match(src, /site\.backup_restore/);
});

test("restore_backup_posts_the_restore_route", async () => {
  const calls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: opts?.body ? JSON.parse(opts.body) : undefined });
    return { status: 201, json: async () => ({ ok: true, unit_id: 1, checkrun_pk: 9 }) };
  };
  const { status } = await restoreBackup(4, 1, { checkrun_pk: 9, confirm_name: "bare" });
  assert.equal(status, 201);
  assert.equal(calls[0].url, "/api/v1/sites/4/backups/1/restore/");
  assert.deepEqual(calls[0].body, { checkrun_pk: 9, confirm_name: "bare" });
});

test("test_backup_now_posts_the_test_route", async () => {
  const calls: Array<{ url: string }> = [];
  (globalThis as any).fetch = async (url: string) => {
    calls.push({ url });
    return {
      status: 201,
      json: async () => ({
        schema_version: 1, unit_id: 1, site_id: 4, bytes: 128,
        digest: "b".repeat(64), stored_at: "2026-08-23T03:00:00+00:00",
      }),
    };
  };
  const { status } = await testBackupNow(4, 1);
  assert.equal(status, 201);
  assert.equal(calls[0].url, "/api/v1/sites/4/backups/1/test/");
});
