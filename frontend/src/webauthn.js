// WebAuthn ceremonies shared by Login, Enroll, Settings, and the T1 overlay.
// T4 Playwright is SLIP; protocol tests inject apiFn / getAssertion / createCredential.
import { api } from "./api.js";

export async function performHardwareTouch({
  apiFn = api,
  getAssertion = (opts) => navigator.credentials.get({ publicKey: opts }),
} = {}) {
  const begin = await apiFn("auth/webauthn/authentication/begin/", {});
  if (begin.status !== 200) return begin;
  let assertion;
  try {
    assertion = await getAssertion(begin.data);
  } catch (err) {
    return { status: 0, data: { detail: err?.message || "Passkey was cancelled" } };
  }
  return apiFn("auth/webauthn/touch/", assertion);
}

export async function registerPasskey(name, {
  apiFn = api,
  createCredential = (opts) => navigator.credentials.create({ publicKey: opts }),
} = {}) {
  const begin = await apiFn("auth/webauthn/registration/begin/", {});
  if (begin.status !== 200 && begin.status !== 201) return begin;
  let cred;
  try {
    cred = await createCredential(begin.data);
  } catch (err) {
    return { status: 0, data: { detail: err?.message || "Passkey was cancelled" } };
  }
  const body = (cred && typeof cred === "object") ? { ...cred, name } : { name };
  return apiFn("auth/webauthn/registration/complete/", body);
}
