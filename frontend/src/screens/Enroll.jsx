// First-run: WebAuthn, then recovery-codes-once, then a phone passkey prompt.
// TOTP is Settings fallback, not this screen.
import React, { useEffect, useState } from "react";
import { registerPasskey } from "../webauthn.js";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

export function Enroll({ onDone }) {
  const [recovery, setRecovery] = useState(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [phonePrompt, setPhonePrompt] = useState(false);

  useEffect(() => {
    if (!recovery) return;
    const warn = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [recovery]);

  async function register(name) {
    setError("");
    const { status, data } = await registerPasskey(name);
    if (status !== 200 && status !== 201) {
      setError(data.detail || "Enrollment did not complete");
      return;
    }
    if (data.recovery_codes) setRecovery(data.recovery_codes);
    setCount(data.webauthn_count || count + 1);
    if ((data.webauthn_count || count + 1) >= 2) onDone();
    else if (!data.recovery_codes) setPhonePrompt(true);
  }

  if (recovery && !phonePrompt)
    return (
      <div style={{ maxWidth: 420, margin: "10vh auto" }}>
        <h2>Recovery codes — shown once</h2>
        <p>Store these offline (password manager / paper). Each works exactly once.</p>
        <pre style={{ ...box, lineHeight: 1.8 }}>{recovery.join("\n")}</pre>
        <button style={{ padding: 8, marginRight: 8 }}
          onClick={() => navigator.clipboard.writeText(recovery.join("\n"))
            .then(() => setCopied("ok"), () => setCopied("failed"))}>
          {copied === "ok" ? "Copied ✔"
            : copied === "failed" ? "Copy failed — select the codes manually"
            : "Copy to clipboard"}
        </button>
        <button style={{ padding: 8 }} onClick={() => setPhonePrompt(true)}>
          I saved them — continue
        </button>
      </div>
    );

  if (phonePrompt)
    return (
      <div style={{ maxWidth: 420, margin: "10vh auto" }}>
        <h2>Add a passkey on this phone</h2>
        <p>Two WebAuthn credentials are required before T1 actions are available.
          Register a platform passkey on the phone you carry.</p>
        <button style={{ padding: 8, marginRight: 8 }}
          onClick={() => register("phone")}>Register phone passkey</button>
        <button style={{ padding: 8 }} onClick={onDone}>Skip for now</button>
        {error && <div style={{ color: "#ff7b72" }}>{error}</div>}
      </div>
    );

  return (
    <div style={{ maxWidth: 420, margin: "10vh auto" }}>
      <h2>Set up a passkey</h2>
      <p>2FA is mandatory. Register a security key, then a passkey on this phone.
        TOTP is a Settings fallback, not this first-run.</p>
      <button style={{ padding: 8 }} onClick={() => register("security-key")}>
        Register a security key
      </button>
      {error && <div style={{ color: "#ff7b72" }}>{error}</div>}
    </div>
  );
}

export default Enroll;
