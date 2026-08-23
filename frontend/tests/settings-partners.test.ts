// Settings Partners tab: Create partner (not Connect), 201 hubk_/whsec_ once,
// Enroll once-panel, Fake/empty INTAKE_URL never Connected, F8 product-tab
// render, Sites All/Mine/Partner + badge, hide adopt/job-create, Findings
// entity partner:{slug}.
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };
(globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

import {
  SETTINGS_TABS,
  PartnersPanel,
  PartnerEnrollOnce,
  createPartner,
  partnersList,
  intakeLine,
} from "../src/screens/Settings.jsx";
import { ActionButton, T1Overlay } from "../src/Tiers.jsx";
import { tierFor } from "../src/actions.js";
import {
  PartnerBadge, SiteStatus, SitesView, isPartnerSite,
} from "../src/screens/Sites.jsx";
import { FindingsView } from "../src/screens/Findings.jsx";
import { NAV } from "../src/Chrome.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

const PARTNER_SITE = {
  id: 90,
  name: "fixture-site",
  domain: "app.fixture-partner.test",
  project: "fixture-project",
  partner: true,
  latest_manifest_version: 1,
  manifest_current: true,
  edge_owner: "host_caddy",
  job_create: true,
  adopt: { stage: "plan", volumes: ["data"] },
};

test("settings_tabs_partners_after_aws_is_create_partner_not_connect", () => {
  assert.deepEqual(SETTINGS_TABS.map((t) => t.id),
    ["security", "cloudflare", "aws", "partners", "developer", "vault"]);
  assert.equal(SETTINGS_TABS.find((t) => t.id === "partners")?.label, "Partners");
  assert.equal(NAV.length, 6);

  const markup = render(PartnersPanel, {
    partners: [],
    intake: { status: "degraded", mode: "fake", configured: false },
  });
  const text = visibleText(markup);
  assert.match(text, /Create partner/);
  assert.doesNotMatch(text, /\bConnect\b/);
  assert.doesNotMatch(text, /\bConnected\b/);
  assert.match(text, /Fake/);
  assert.match(text, /degraded/i);
  assert.match(text, /No partners yet/);
  assert.doesNotMatch(text, /\binstance\b/i);
  assert.doesNotMatch(text, /99\.9%|uptime SLA/i);
  assert.match(text, /response-time/);
  assert.equal((markup.match(/<button/g) || []).length, 1,
    "empty Partners tab is one sentence + the T1 Create partner button");
});

test("unconfigured_and_post_create_fake_intake_never_connected", () => {
  const empty = visibleText(render(PartnersPanel, {
    partners: [],
    intake: { status: "degraded", mode: "fake", configured: false },
  }));
  assert.match(empty, /Fake/);
  assert.doesNotMatch(empty, /\bConnected\b/);

  const after = visibleText(render(PartnersPanel, {
    partners: [{ id: 1, slug: "fixture-partner", name: "fixture-partner",
      destination_order: [] }],
    intake: { status: "degraded", mode: "fake", configured: false },
  }));
  assert.match(after, /fixture-partner/);
  assert.match(after, /partner-site create will refuse/);
  assert.match(after, /dedicated cloud first/);
  assert.match(after, /Fake/);
  assert.doesNotMatch(after, /\bConnected\b/);
  assert.doesNotMatch(after, /hubk_/);
  assert.doesNotMatch(after, /whsec_/);

  const err = visibleText(render(PartnersPanel, {
    partners: [],
    intake: {
      status: "error", mode: "fake", configured: false,
      as_of: "2026-08-24T02:03:04Z",
    },
  }));
  assert.match(err, /error/i);
  assert.match(err, /data as of/);
  assert.doesNotMatch(err, /\bConnected\b/);
});

test("enroll_once_panel_shows_prefixes_then_dismiss_clears_them", async () => {
  const hubk = "hubk_test_once-material";
  const whsec = "whsec_once-material";
  const shown = render(PartnerEnrollOnce, {
    hubk, whsec, onSaved: () => {},
  });
  const shownText = visibleText(shown);
  assert.match(shownText, /hubk_test_/);
  assert.match(shownText, /whsec_/);
  assert.match(shownText, /I saved them/);
  assert.match(shownText, /Copy/);

  const gone = visibleText(render(PartnersPanel, {
    partners: [{ id: 1, slug: "fixture-partner", destination_order: [] }],
    intake: { status: "degraded", mode: "fake", configured: false },
    minted: null,
  }));
  assert.doesNotMatch(gone, /hubk_/);
  assert.doesNotMatch(gone, /whsec_/);
  assert.doesNotMatch(gone, /hubk_test_once-material/);
  assert.doesNotMatch(gone, /whsec_once-material/);

  const calls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: opts?.body ? JSON.parse(opts.body) : undefined });
    return {
      status: 201,
      json: async () => ({
        id: 1, slug: "fixture-partner", name: "fixture-partner",
        hubk, whsec,
      }),
    };
  };
  const created = await createPartner("fixture-partner", "fixture-partner");
  assert.equal(created.status, 201);
  assert.equal(calls[0].url, "/api/v1/partners/");
  assert.equal(calls[0].body.confirm_name, "fixture-partner");
  assert.equal(calls[0].body.slug, "fixture-partner");
  assert.equal(created.data.hubk, hubk);
  assert.equal(created.data.whsec, whsec);

  (globalThis as any).fetch = async (url: string) => {
    assert.equal(url, "/api/v1/partners/");
    return {
      status: 200,
      json: async () => ({
        partners: [{ id: 1, slug: "fixture-partner", destination_order: [] }],
        intake: { status: "degraded", mode: "fake", configured: false },
      }),
    };
  };
  const listed = await partnersList();
  assert.equal(listed.status, 200);
  const dumped = JSON.stringify(listed.data);
  assert.ok(!dumped.includes("hubk_"), dumped);
  assert.ok(!dumped.includes("whsec_"), dumped);
  assert.doesNotMatch(dumped, /\bConnected\b/);
});

test("partner_create_t1_overlay_omits_cost", () => {
  assert.equal(tierFor("partner.create").tier, "T1");
  assert.equal(tierFor("partner.create").label, "Create partner");
  const overlay = visibleText(render(T1Overlay, {
    label: "Create partner",
    onTouch: () => {}, onConfirm: () => {}, onDismiss: () => {},
  }));
  assert.match(overlay, /Create partner/);
  assert.doesNotMatch(overlay, /\$0\.05/);
  assert.doesNotMatch(overlay, /hourly cost/i);
  assert.doesNotMatch(overlay, /\binstance\b/i);
  const rest = visibleText(render(ActionButton, {
    row: tierFor("partner.create"), onRun: () => {},
  }));
  assert.match(rest, /Create partner/);
  assert.doesNotMatch(rest, /\$0\.05/);
});

test("sites_all_mine_partner_filter_and_partner_badge", () => {
  assert.equal(isPartnerSite(PARTNER_SITE), true);
  assert.equal(isPartnerSite({ id: 1, name: "shop" }), false);
  const badge = visibleText(render(PartnerBadge, { site: PARTNER_SITE }));
  assert.match(badge, /◆/);
  assert.match(badge, /partner/);

  const markup = render(SitesView, {
    phase: "live",
    sites: [
      { id: 1, name: "shop", domain: "shop.example.com", project: "shop" },
      PARTNER_SITE,
    ],
    onSelect: () => {}, onNav: () => {},
  });
  const text = visibleText(markup);
  assert.match(text, /All/);
  assert.match(text, /Mine/);
  assert.match(text, /Partner/);
  assert.match(text, /◆ partner/);
});

test("hide_adopt_and_job_create_on_partner_site_detail", () => {
  const partner = visibleText(render(SiteStatus, {
    site: PARTNER_SITE, actions: [],
    backups: { units: [] },
  }));
  assert.doesNotMatch(partner, /Adopt plan/);
  assert.doesNotMatch(partner, /Start adopt/);
  assert.doesNotMatch(partner, /Create job/);

  const mine = visibleText(render(SiteStatus, {
    site: {
      id: 1, name: "shop", domain: "shop.example.com", project: "shop",
      edge_owner: "host_caddy",
      adopt: { stage: "plan", volumes: ["data"] },
      job_create: true,
    },
    actions: [],
    backups: { units: [] },
  }));
  assert.match(mine, /Adopt plan/);
  assert.match(mine, /Create job/);
});

test("findings_entity_filter_includes_partner_slug", () => {
  const finding = {
    id: 40,
    source_engine: "intake",
    severity: "p1",
    entity: "partner:fixture-partner",
    title: "Intake unreachable",
    body: "last successful intake probe is older than five minutes",
    state: "open",
    fingerprint: "partner-intake-unreachable",
  };
  const markup = render(FindingsView, {
    phase: "live",
    findings: [finding],
    filter: { entity: "partner:fixture-partner" },
    onFilter: () => {},
    onNav: () => {},
  });
  const text = visibleText(markup);
  assert.match(text, /partner:fixture-partner/);
  assert.match(text, /Intake unreachable/);
  assert.match(markup, /aria-label="Filter by entity"/);
});

test("intake_line_names_fake_and_never_connected", () => {
  const degraded = intakeLine({ status: "degraded", mode: "fake", configured: false });
  assert.match(degraded, /Fake/);
  assert.match(degraded, /degraded/i);
  assert.doesNotMatch(degraded, /\bConnected\b/);
  const error = intakeLine({
    status: "error", mode: "fake", configured: false,
    as_of: "2026-08-24T02:03:04Z",
  });
  assert.match(error, /error/i);
  assert.match(error, /data as of/);
  assert.doesNotMatch(error, /\bConnected\b/);
});
