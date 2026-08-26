// Browser WebAuthn needs ArrayBuffers; django-otp-webauthn (and py_webauthn)
// JSON-serializes challenge / user.id / credential ids as base64url strings.
// Passing those strings to navigator.credentials.create throws TypeError in Chrome.
import { test } from "node:test";
import assert from "node:assert/strict";

function b64(s: string) {
  return Buffer.from(s).toString("base64url");
}

test("registration_begin_json_is_converted_to_arraybuffers_before_create", async () => {
  const seen: any[] = [];
  const completeBodies: any[] = [];
  const { registerPasskey } = await import("../src/webauthn.js");
  const result = await registerPasskey("security-key", {
    apiFn: async (path: string, body: any) => {
      if (path.includes("registration/begin"))
        return {
          status: 200,
          data: {
            challenge: b64("challenge"),
            rp: { id: "localhost", name: "Deploy Hub" },
            user: { id: b64("user"), name: "j", displayName: "j" },
            pubKeyCredParams: [{ type: "public-key", alg: -7 }],
            excludeCredentials: [{ type: "public-key", id: b64("excl") }],
          },
        };
      completeBodies.push(body);
      return { status: 200, data: { webauthn_count: 1, recovery_codes: ["a"] } };
    },
    createCredential: async (opts: any) => {
      seen.push(opts);
      return {
        id: "cred-id",
        rawId: new Uint8Array([1, 2, 3]).buffer,
        type: "public-key",
        authenticatorAttachment: "cross-platform",
        getClientExtensionResults: () => ({ credProps: { rk: false } }),
        response: {
          attestationObject: new Uint8Array([4, 5]).buffer,
          clientDataJSON: new Uint8Array([6, 7]).buffer,
          getTransports: () => ["usb"],
        },
      };
    },
  });

  assert.equal(result.status, 200);
  assert.equal(seen.length, 1);
  assert.equal(seen[0].challenge instanceof ArrayBuffer, true, "challenge must be ArrayBuffer");
  assert.equal(seen[0].user.id instanceof ArrayBuffer, true, "user.id must be ArrayBuffer");
  assert.equal(
    seen[0].excludeCredentials[0].id instanceof ArrayBuffer,
    true,
    "excludeCredentials[].id must be ArrayBuffer",
  );
  const posted = completeBodies[0];
  assert.equal(typeof posted.rawId, "string", "complete body must be JSON-safe");
  assert.equal(typeof posted.response.attestationObject, "string");
  assert.equal(typeof posted.response.clientDataJSON, "string");
  assert.equal(posted.name, "security-key");
  assert.deepEqual(posted.response.transports, ["usb"]);
});

test("authentication_begin_json_is_converted_to_arraybuffers_before_get", async () => {
  const seen: any[] = [];
  const touchBodies: any[] = [];
  const { performHardwareTouch } = await import("../src/webauthn.js");
  const result = await performHardwareTouch({
    apiFn: async (path: string, body: any) => {
      if (path.includes("authentication/begin"))
        return {
          status: 200,
          data: {
            challenge: b64("authchall"),
            rpId: "localhost",
            allowCredentials: [{ type: "public-key", id: b64("cred") }],
          },
        };
      touchBodies.push(body);
      return { status: 200, data: { touched: true } };
    },
    getAssertion: async (opts: any) => {
      seen.push(opts);
      return {
        id: "cred-id",
        rawId: new Uint8Array([1, 2, 3]).buffer,
        type: "public-key",
        getClientExtensionResults: () => ({}),
        response: {
          authenticatorData: new Uint8Array([4]).buffer,
          clientDataJSON: new Uint8Array([5]).buffer,
          signature: new Uint8Array([6]).buffer,
          userHandle: new Uint8Array([7]).buffer,
        },
      };
    },
  });

  assert.equal(result.status, 200);
  assert.equal(seen[0].challenge instanceof ArrayBuffer, true);
  assert.equal(seen[0].allowCredentials[0].id instanceof ArrayBuffer, true);
  assert.equal(typeof touchBodies[0].rawId, "string");
  assert.equal(typeof touchBodies[0].response.signature, "string");
});
