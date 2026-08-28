// Extracted so ?sim=login can mount this without the Shell (C9 / UX-F8).
import React, { useState } from "react";
import { api } from "../api.js";
import { parseRequestOptionsJSON, serializeCredential } from "../webauthn.js";

import { box } from "../ui/surface.js";

export function Login({ onLogin }) {
  const [form, setForm] = useState({ username: "", password: "", otp_code: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [useTotp, setUseTotp] = useState(false);

  async function hydrateUser(partial) {
    const me = await api("auth/me/");
    if (me.status === 200 && me.data?.authenticated) return me.data;
    return { ...partial, authenticated: true };
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    const { status, data } = await api("auth/login/", form);
    if (status === 200) onLogin(await hydrateUser(data));
    else setError(data.detail || "Login failed");
    setBusy(false);
  }

  async function passkey(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const begin = await api("auth/webauthn/login/begin/", { username: form.username });
    if (begin.status !== 200) {
      setBusy(false);
      setError(begin.data.detail || "Passkey sign-in failed to start");
      return;
    }
    let assertion = { id: "sim", response: {} };
    if (typeof navigator !== "undefined" && navigator.credentials?.get) {
      try {
        assertion = serializeCredential(
          await navigator.credentials.get({
            publicKey: parseRequestOptionsJSON(begin.data),
          }),
        );
      } catch (err) {
        setBusy(false);
        setError(err?.message || "Passkey was cancelled");
        return;
      }
    }
    const { status, data } = await api("auth/login/", {
      username: form.username, password: form.password, webauthn: assertion,
    });
    if (status === 200) onLogin(await hydrateUser(data));
    else setError(data.detail || "Passkey sign-in failed");
    setBusy(false);
  }

  return (
    <form onSubmit={useTotp ? submit : passkey}
      style={{ maxWidth: 320, margin: "15vh auto", display: "grid", gap: 8 }}>
      <h2>Deploy Hub</h2>
      <input type="text" style={box} aria-label="username" placeholder="username"
        value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
      <input type="password" style={box} aria-label="password" placeholder="password"
        value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
      {useTotp ? (
        <input type="text" style={box} aria-label="TOTP or recovery code"
          placeholder="TOTP or recovery code (if enrolled)"
          value={form.otp_code}
          onChange={(e) => setForm({ ...form, otp_code: e.target.value })} />
      ) : (
        <p style={{ color: "var(--hud-muted)", margin: 0 }}>
          Sign in with a passkey / security key.
        </p>
      )}
      <button style={{ padding: 8 }} disabled={busy}>
        {busy ? "Signing in…" : (useTotp ? "Log in" : "Sign in with passkey")}
      </button>
      <button type="button" style={{ padding: 8 }}
        onClick={() => setUseTotp((v) => !v)}>
        {useTotp ? "Use a passkey instead" : "Use authenticator code instead"}
      </button>
      {error && <div style={{ color: "var(--hud-danger)" }}>{error}</div>}
    </form>
  );
}

export default Login;
