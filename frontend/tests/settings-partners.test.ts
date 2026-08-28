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
  addDestination, moveDestination, removeDestination,
} from "../src/screens/Settings.jsx";
import { ActionButton, ConfirmDialog, T1Overlay } from "../src/Tiers.jsx";
import { makeTierRunner, tierFor } from "../src/actions.js";
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
    systemAdmin: true,
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
  assert.match(text, /Enable partner API/);
  assert.doesNotMatch(markup, /type="checkbox"/);
  assert.doesNotMatch(markup, /role="switch"/);

  const tenant = visibleText(render(PartnersPanel, {
    partners: [],
    intake: { status: "degraded", mode: "fake", configured: false },
  }));
  assert.doesNotMatch(tenant, /Enable partner API/);
  assert.doesNotMatch(tenant, /Disable partner API/);
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

test("partner_create_confirm_step_up_with_non_empty_name_runs", async () => {
  // ActionButton always click({ expected: confirmName }). Empty-string
  // expected is defined, so typed slug !== "" refuses and empty fails
  // !name — omit confirmName (same as instance.create) so the typed
  // name is the slug and confirmStepUp onRuns.
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const { act, create } = await import("react-test-renderer");

  let tree: any;
  act(() => {
    tree = create(React.createElement(PartnersPanel, {
      partners: [],
      intake: { status: "degraded", mode: "fake", configured: false },
    }));
  });
  const wired = tree.root.findAllByType(ActionButton)
    .find((n: any) => n.props.row.id === "partner.create");
  assert.ok(wired, "Create partner ActionButton must still be wired");
  assert.equal(wired.props.row.id, "partner.create");
  const confirmName = wired.props.confirmName;
  act(() => { tree.unmount(); });

  const ran: any[] = [];
  const runner = makeTierRunner({
    row: tierFor("partner.create"),
    onRun: (args: any) => ran.push(args),
  });
  runner.click({ expected: confirmName });
  runner.touch();
  runner.confirmStepUp({ name: "fixture-partner" });
  assert.equal(ran.length, 1, "typed slug must onRun when confirmName is omitted");
  assert.equal(ran[0].name, "fixture-partner");
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

test("enable_is_t1_not_a_toggle_and_suspend_names_stop_detach_revoke", () => {
  assert.equal(tierFor("partner.api_kill_switch").tier, "T1");
  assert.equal(tierFor("partner.suspend").tier, "T1");
  const enable = visibleText(render(ActionButton, {
    row: { ...tierFor("partner.api_kill_switch"), label: "Enable partner API" },
    confirmName: "partner-api",
    onRun: () => {},
  }));
  assert.match(enable, /Enable partner API/);
  assert.doesNotMatch(enable, /type="checkbox"|role="switch"/);

  const overlay = visibleText(render(T1Overlay, {
    label: "Suspend partner",
    summary: "Stop containers, detach routes, revoke the Hub-side key.",
    onTouch: () => {}, onConfirm: () => {}, onDismiss: () => {},
  }));
  assert.match(overlay, /Stop containers/);
  assert.match(overlay, /detach routes/);
  assert.match(overlay, /revoke/);
  assert.doesNotMatch(overlay, /\$0\.05/);
  assert.doesNotMatch(overlay, /\binstance\b/i);

  const otherT1 = visibleText(render(T1Overlay, {
    label: "Delete target",
    onTouch: () => {}, onConfirm: () => {}, onDismiss: () => {},
  }));
  assert.doesNotMatch(otherT1, /Stop containers/);
  assert.doesNotMatch(otherT1, /\$0\.05/);
});

test("ranker_own_server_honesty_sentence_and_never_connected", () => {
  assert.equal(tierFor("partner.destination_rank").tier, "T2");
  const honesty = "abuse takedowns and IP-reputation damage land on hardware and residential/office connections you cannot dispose of";
  const dialog = visibleText(render(ConfirmDialog, {
    label: "Rank partner destination",
    summary: honesty,
    onConfirm: () => {}, onDismiss: () => {},
  }));
  assert.match(dialog, /abuse takedowns/);
  assert.match(dialog, /IP-reputation/);

  const ranked = visibleText(render(PartnersPanel, {
    partners: [{
      id: 1, slug: "fixture-partner",
      destination_order: [1],
      destinations: [{ id: 1, host: "home.fixture.test", kind: "ssh" }],
    }],
    intake: { status: "degraded", mode: "fake", configured: false },
  }));
  assert.match(ranked, /Rank partner destination|fixture-partner/);
  assert.match(ranked, /dedicated cloud first/);
  assert.doesNotMatch(ranked, /\bConnected\b/);
  assert.doesNotMatch(ranked, /\binstance\b/i);
  assert.match(ranked, /Create partner|Suspend partner|Enable partner API/);
});

test("takedown_control_on_partner_site_detail", () => {
  assert.equal(tierFor("partner.site_takedown").tier, "T2");
  const partner = visibleText(render(SiteStatus, {
    site: PARTNER_SITE, actions: [],
    backups: { units: [] },
  }));
  assert.match(partner, /Take down site/);
  assert.match(partner, /410/);
  assert.doesNotMatch(partner, /Adopt plan/);
  assert.doesNotMatch(partner, /\binstance\b/i);

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
  assert.doesNotMatch(mine, /Take down site/);
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

test("suspended_partner_row_names_suspended_in_words", () => {
  const live = visibleText(render(PartnersPanel, {
    partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
      suspended: false }],
    intake: { status: "degraded", mode: "fake", configured: false },
  }));
  assert.match(live, /fixture-partner/);
  assert.doesNotMatch(live, /Suspended/);

  const stopped = visibleText(render(PartnersPanel, {
    partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
      suspended: true }],
    intake: { status: "degraded", mode: "fake", configured: false },
  }));
  assert.match(stopped, /fixture-partner/);
  assert.match(stopped, /Suspended/);
  assert.doesNotMatch(stopped, /\bConnected\b/);
  assert.doesNotMatch(stopped, /\binstance\b/i);
});

test("rank_draft_helpers_add_reorder_remove", () => {
  assert.deepEqual(addDestination([], 2), [2]);
  assert.deepEqual(addDestination([2], 2), [2]);
  assert.deepEqual(moveDestination([1, 2, 3], 3, -1), [1, 3, 2]);
  assert.deepEqual(moveDestination([1, 2], 1, -1), [1, 2]);
  assert.deepEqual(removeDestination([1, 2], 1), [2]);
});

test("ranker_posts_draft_order_not_stored_empty", async () => {
  const CANDS = [
    { id: 7, host: "cloud.rank.test", kind: "aws_ec2", tunnel: false },
    { id: 8, host: "home.rank.test", kind: "ssh", tunnel: true },
  ];
  const markup = render(PartnersPanel, {
    partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
      destinations: [], suspended: false }],
    intake: { status: "degraded", mode: "fake", configured: false },
    candidateTargets: CANDS,
    rankDrafts: { 1: [7, 8] },
  });
  const text = visibleText(markup);
  assert.match(text, /cloud.rank.test/);
  assert.match(text, /home.rank.test/);
  assert.match(text, /Add destination/);
  assert.doesNotMatch(text, /\bConnected\b/);
  assert.doesNotMatch(text, /\binstance\b/i);

  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const { act, create } = await import("react-test-renderer");
  const calls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: opts?.body ? JSON.parse(opts.body) : undefined });
    return { status: 200, json: async () => ({ id: 1, slug: "fixture-partner",
      destination_order: [7, 8], destinations: CANDS }) };
  };
  let tree: any;
  act(() => {
    tree = create(React.createElement(PartnersPanel, {
      partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
        destinations: [], suspended: false }],
      intake: { status: "degraded", mode: "fake", configured: false },
      candidateTargets: CANDS,
      rankDrafts: { 1: [7, 8] },
    }));
  });
  const rankBtn = tree.root.findAllByType(ActionButton)
    .find((n: any) => n.props.row.id === "partner.destination_rank");
  assert.ok(rankBtn);
  assert.match(String(rankBtn.props.summary), /abuse takedowns/);
  await rankBtn.props.onRun();
  const posted = calls.find((c) => String(c.url).includes("destination-rank"));
  assert.ok(posted, "Rank must POST destination-rank");
  assert.deepEqual(posted.body.destination_order, [7, 8]);
  act(() => { tree.unmount(); });
});

test("ranker_posts_empty_draft_not_stored_order", async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const { act, create } = await import("react-test-renderer");
  const calls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: opts?.body ? JSON.parse(opts.body) : undefined });
    return { status: 200, json: async () => ({ id: 1, slug: "fixture-partner",
      destination_order: [], destinations: [] }) };
  };
  let tree: any;
  act(() => {
    tree = create(React.createElement(PartnersPanel, {
      partners: [{ id: 1, slug: "fixture-partner", destination_order: [7],
        destinations: [{ id: 7, host: "cloud.rank.test", kind: "aws_ec2" }],
        suspended: false }],
      intake: { status: "degraded", mode: "fake", configured: false },
      candidateTargets: [{ id: 7, host: "cloud.rank.test", kind: "aws_ec2", tunnel: false }],
      rankDrafts: { 1: [] },
    }));
  });
  const rankBtn = tree.root.findAllByType(ActionButton)
    .find((n: any) => n.props.row.id === "partner.destination_rank");
  await rankBtn.props.onRun();
  const posted = calls.find((c) => String(c.url).includes("destination-rank"));
  assert.ok(posted, "Rank must POST destination-rank");
  assert.deepEqual(posted.body.destination_order, []);
  act(() => { tree.unmount(); });
});

test("ranker_open_ssh_draft_is_honesty_and_picker_is_not_a_toggle", async () => {
  const CANDS = [
    { id: 7, host: "cloud.rank.test", kind: "aws_ec2", tunnel: false },
    { id: 8, host: "open.rank.test", kind: "ssh", tunnel: false },
  ];
  const markup = render(PartnersPanel, {
    partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
      destinations: [], suspended: false }],
    intake: { status: "degraded", mode: "fake", configured: false },
    candidateTargets: CANDS,
    rankDrafts: { 1: [8] },
  });
  assert.doesNotMatch(markup, /type="checkbox"/);
  assert.doesNotMatch(markup, /role="switch"/);

  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const { act, create } = await import("react-test-renderer");
  let tree: any;
  act(() => {
    tree = create(React.createElement(PartnersPanel, {
      partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
        destinations: [], suspended: false }],
      intake: { status: "degraded", mode: "fake", configured: false },
      candidateTargets: CANDS,
      rankDrafts: { 1: [8] },
    }));
  });
  const rankBtn = tree.root.findAllByType(ActionButton)
    .find((n: any) => n.props.row.id === "partner.destination_rank");
  assert.ok(rankBtn);
  assert.match(String(rankBtn.props.summary), /abuse takedowns/);
  act(() => { tree.unmount(); });
});

test("rank_summary_helper_is_gone", async () => {
  const src = await import("node:fs/promises");
  const text = await src.readFile(
    new URL("../src/screens/Settings.jsx", import.meta.url), "utf8",
  );
  assert.doesNotMatch(text, /export function rankSummary/);
});

