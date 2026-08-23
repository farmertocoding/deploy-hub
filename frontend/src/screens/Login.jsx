// Extracted so ?sim=login can mount this without the Shell (C9 / UX-F8).
import React, { useState } from "react";
import { api } from "../api.js";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

export function Login({ onLogin }) {
  const [form, setForm] = useState({ username: "", password: "", otp_code: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [useTotp, setUseTotp] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    const { status, data } = await api("auth/login/", form);
    setBusy(false);
    if (status === 200) onLogin({ ...data, authenticated: true });
    else setError(data.detail || "Login failed");
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
        assertion = await navigator.credentials.get({ publicKey: begin.data });
      } catch (err) {
        setBusy(false);
        setError(err?.message || "Passkey was cancelled");
        return;
      }
    }
    const { status, data } = await api("auth/login/", {
      username: form.username, password: form.password, webauthn: assertion,
    });
    setBusy(false);
    if (status === 200) onLogin({ ...data, authenticated: true });
    else setError(data.detail || "Passkey sign-in failed");
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
        <p style={{ color: "#8b949e", margin: 0 }}>
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
      {error && <div style={{ color: "#ff7b72" }}>{error}</div>}
    </form>
  );
}

export default Login;
