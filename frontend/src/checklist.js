// §F3 first-run card copy + derived remaining items. Progress itself comes
// from GET /api/v1/first-run/ (server-derived). This module does not invent
// a topic — Home refreshes on the existing `findings` client.

export const CHECKLIST_COPY = {
  enroll_target: {
    sentence: "Enroll the first target — provision a machine and it appears in the fleet.",
    button: "Copy the provision command",
  },
  connect_cloudflare: {
    sentence: "Connect Cloudflare — paste a single-zone token so public sites can bind a zone.",
    button: "Connect Cloudflare",
  },
  plant_origin_ca: {
    sentence: "Plant the Origin-CA key from a Hub-local file — required before the first proxied public deploy.",
    button: "Plant Origin-CA",
  },
  add_project: {
    sentence: "Add a project — the create that binds the DNS zone and primary target.",
    button: "Add a project",
  },
};

export function remainingItems(progress) {
  return (progress?.items || []).filter((item) => item.applicable && !item.done);
}

export function checklistOwnsHome(progress) {
  return Boolean(progress?.owns_home);
}
