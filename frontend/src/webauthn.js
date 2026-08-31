// WebAuthn ceremonies shared by Login, Enroll, Settings, and the T1 overlay.
// T4 Playwright is SLIP; protocol tests inject apiFn / getAssertion / createCredential.
//
// django-otp-webauthn JSON (py_webauthn options_to_json_dict) sends challenge,
// user.id and credential ids as base64url strings. The WebAuthn API requires
// ArrayBuffers; passing the strings throws TypeError in the browser. Complete
// endpoints parse JSON via parse_registration_credential_json, so ArrayBuffers
// must be turned back into base64url before fetch.
import { api, simState } from "./api.js";

const LOCALHOST_WEBAUTHN =
  "Passkeys require this page at http://localhost — WebAuthn cannot use 127.0.0.1.";

function originCannotUseWebAuthn(hostname) {
  const host = hostname ?? (typeof window !== "undefined" ? window.location.hostname : "");
  return host === "127.0.0.1" || host === "::1" || host === "[::1]"
    || /^\d{1,3}(?:\.\d{1,3}){3}$/.test(host);
}

function b64urlToBuffer(value) {
  if (value == null || value instanceof ArrayBuffer) return value;
  if (ArrayBuffer.isView(value)) {
    return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength);
  }
  const padded = String(value).replace(/-/g, "+").replace(/_/g, "/");
  const pad = (4 - (padded.length % 4)) % 4;
  const bin = atob(padded.padEnd(padded.length + pad, "="));
  const out = new ArrayBuffer(bin.length);
  const view = new Uint8Array(out);
  for (let i = 0; i < bin.length; i += 1) view[i] = bin.charCodeAt(i);
  return out;
}

function bufferToB64url(value) {
  if (value == null || typeof value === "string") return value;
  const view = value instanceof ArrayBuffer
    ? new Uint8Array(value)
    : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  let bin = "";
  for (const byte of view) bin += String.fromCharCode(byte);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

function isBufferSource(value) {
  return value instanceof ArrayBuffer || ArrayBuffer.isView(value);
}

export function parseCreationOptionsJSON(opts) {
  if (!opts || typeof opts !== "object") return opts;
  return {
    ...opts,
    challenge: b64urlToBuffer(opts.challenge),
    user: opts.user ? { ...opts.user, id: b64urlToBuffer(opts.user.id) } : opts.user,
    excludeCredentials: (opts.excludeCredentials || []).map((cred) => ({
      ...cred,
      id: b64urlToBuffer(cred.id),
    })),
  };
}

export function parseRequestOptionsJSON(opts) {
  if (!opts || typeof opts !== "object") return opts;
  return {
    ...opts,
    challenge: b64urlToBuffer(opts.challenge),
    allowCredentials: (opts.allowCredentials || []).map((cred) => ({
      ...cred,
      id: b64urlToBuffer(cred.id),
    })),
  };
}

export function serializeCredential(cred, extra = {}) {
  if (!cred || typeof cred !== "object") return { ...extra };
  const body = { ...extra, id: cred.id, type: cred.type };
  if (cred.rawId != null) {
    body.rawId = isBufferSource(cred.rawId) ? bufferToB64url(cred.rawId) : cred.rawId;
  }
  if (cred.authenticatorAttachment) {
    body.authenticatorAttachment = cred.authenticatorAttachment;
  }
  if (typeof cred.getClientExtensionResults === "function") {
    body.clientExtensionResults = cred.getClientExtensionResults();
  } else if (cred.clientExtensionResults) {
    body.clientExtensionResults = cred.clientExtensionResults;
  }
  const resp = cred.response;
  if (resp && typeof resp === "object") {
    body.response = {};
    for (const key of [
      "attestationObject", "clientDataJSON", "authenticatorData", "signature", "userHandle",
    ]) {
      if (resp[key] == null) continue;
      body.response[key] = isBufferSource(resp[key]) ? bufferToB64url(resp[key]) : resp[key];
    }
    if (typeof resp.getTransports === "function") {
      body.response.transports = resp.getTransports();
    } else if (resp.transports) {
      body.response.transports = resp.transports;
    }
  }
  return body;
}

export async function performHardwareTouch({
  apiFn = api,
  getAssertion = (opts) => navigator.credentials.get({ publicKey: opts }),
} = {}) {
  const begin = await apiFn("auth/webauthn/authentication/begin/", {});
  if (begin.status !== 200) return begin;
  if (simState()) {
    return apiFn("auth/webauthn/touch/", { id: "sim", type: "public-key", response: {} });
  }
  if (originCannotUseWebAuthn()) {
    return { status: 0, data: { detail: LOCALHOST_WEBAUTHN } };
  }
  let assertion;
  try {
    assertion = await getAssertion(parseRequestOptionsJSON(begin.data));
  } catch (err) {
    return { status: 0, data: { detail: err?.message || "Passkey was cancelled" } };
  }
  return apiFn("auth/webauthn/touch/", serializeCredential(assertion));
}

export async function registerPasskey(name, {
  apiFn = api,
  createCredential = (opts) => navigator.credentials.create({ publicKey: opts }),
} = {}) {
  const begin = await apiFn("auth/webauthn/registration/begin/", {});
  if (begin.status !== 200 && begin.status !== 201) return begin;
  if (simState()) {
    return apiFn(
      "auth/webauthn/registration/complete/",
      { id: "sim", type: "public-key", response: {}, name },
    );
  }
  if (originCannotUseWebAuthn()) {
    return { status: 0, data: { detail: LOCALHOST_WEBAUTHN } };
  }
  let cred;
  try {
    cred = await createCredential(parseCreationOptionsJSON(begin.data));
  } catch (err) {
    return { status: 0, data: { detail: err?.message || "Passkey was cancelled" } };
  }
  return apiFn(
    "auth/webauthn/registration/complete/",
    serializeCredential(cred, { name }),
  );
}
