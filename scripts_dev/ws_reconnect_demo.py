"""Phase 0 exit demo driver (design note §4 + conformance/demos template checklist):
fresh user → login (password) → forced TOTP enrollment via the UI (QR/otpauth →
confirm → recovery codes) → re-login with TOTP → demo panel → form error → form
warning + confirm → launch → live stream → kill socket mid-stream → reconnect
recovers via snapshot-then-stream with no gap. Screenshots + transcript → /tmp/demo.

Not part of the product; a dev-only driver for the recorded demo
(conformance/demos/phase-0.md). Run with the stack up (redis, daphne, celery, vite).
"""
import base64
import json
import os
import re
import sys
import time

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
django.setup()

from django_otp.oath import totp  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = "/tmp/demo"
BASE = "http://127.0.0.1:5173"
USERNAME = "demo-operator"
PASSWORD = "a-long-demo-password"
transcript = []


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    transcript.append(line)
    print(line, flush=True)


def fresh_user():
    """Fresh operator with no TOTP device — the UI must force enrollment."""
    from django.contrib.auth.models import User

    User.objects.filter(username=USERNAME).delete()
    User.objects.create_user(USERNAME, password=PASSWORD)


def code_from_otpauth(url):
    secret = re.search(r"[?&]secret=([A-Z2-7]+)", url).group(1)
    key = base64.b32decode(secret)
    return f"{totp(key):06d}"


def panel_lines(page):
    return [ln for ln in page.locator("pre").last.inner_text().split("\n") if ln.strip()]


fresh_user()

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    page = browser.new_page()
    # Devtools-style socket kill: keep a handle on the app's WebSocket so the demo
    # can force-close it mid-stream (emulateNetworkConditions does not sever an
    # already-established ws in Chromium).
    page.add_init_script("""
      const RealWS = window.WebSocket;
      window.WebSocket = function (...args) {
        const ws = new RealWS(...args);
        window.__lastWS = ws;
        return ws;
      };
      window.WebSocket.prototype = RealWS.prototype;
    """)

    # -- 1. First login: password only (no device yet) → forced enrollment screen.
    log(f"open {BASE} — fresh user {USERNAME!r}, no TOTP device")
    page.goto(BASE)
    page.get_by_placeholder("username").fill(USERNAME)
    page.get_by_placeholder("password").fill(PASSWORD)
    page.screenshot(path=f"{OUT}/01-login.png")
    page.get_by_role("button", name="Log in").click()
    page.wait_for_selector("text=Set up two-factor auth")
    log("logged in with password; UI forces TOTP enrollment (§6.10 mandatory-2FA)")

    # -- 2. Enrollment via the UI: QR/otpauth → confirm code → recovery codes.
    page.get_by_role("button", name="Start enrollment").click()
    page.wait_for_selector("text=otpauth://")
    otpauth = page.locator("small").inner_text()
    page.screenshot(path=f"{OUT}/02-enroll-qr.png")
    page.get_by_placeholder("6-digit code").fill(code_from_otpauth(otpauth))
    page.get_by_role("button", name="Confirm").click()
    page.wait_for_selector("text=Recovery codes — shown once")
    n_codes = len(panel_lines(page))
    page.screenshot(path=f"{OUT}/03-recovery-codes.png")
    log(f"TOTP enrolled via UI; {n_codes} recovery codes shown once")
    page.get_by_role("button", name="I saved them — continue").click()
    page.wait_for_selector("text=Signed in as")

    # -- 3. Re-login WITH TOTP (proves the second factor is now enforced).
    # Session hydration keeps a reload signed in, so simulate a new browser:
    page.context.clear_cookies()
    page.reload()
    page.get_by_placeholder("username").fill(USERNAME)
    page.get_by_placeholder("password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_selector("text=Invalid or missing OTP code.")
    log("re-login without TOTP rejected (second factor enforced)")
    # django-otp replay protection: the code used at confirm is burned for its
    # 30 s window — wait for the next window before re-login.
    wait_s = 30 - (time.time() % 30) + 0.5
    log(f"waiting {wait_s:.0f}s for the next TOTP window (replay protection)")
    time.sleep(wait_s)
    page.get_by_placeholder("TOTP or recovery code (if enrolled)").fill(
        code_from_otpauth(otpauth))
    page.get_by_role("button", name="Log in").click()
    page.wait_for_selector("text=Signed in as")
    page.wait_for_selector("text=(live)")
    log("re-logged in with password + TOTP; demo panel open; socket live")

    # -- 4. Validated form: error first (zod client mirror), then warning (server 409).
    page.locator('input[name="name"]').fill("BAD NAME")
    page.get_by_role("button", name="Launch", exact=True).click()
    page.wait_for_selector("text=Lowercase letters, digits and dashes")
    page.screenshot(path=f"{OUT}/04-form-error.png")
    log("form error blocks client-side via generated zod mirror (§4.5)")

    # Legal-but-suspicious input: delay 3.0 passes the zod mirror (≤5.0) but the
    # SERVER warns — 409 + confirm_warnings flow (§4.5).
    page.locator('input[name="name"]').fill("demo")
    page.locator('input[name="delay"]').fill("3")
    page.get_by_role("button", name="Launch", exact=True).click()
    page.wait_for_selector("text=I understand, continue")
    page.screenshot(path=f"{OUT}/05-form-warning.png")
    log("server warning (slow_demo) rendered with 409 + confirm flow")

    # Use a quicker delay for the kill/reconnect segment.
    page.locator('input[name="delay"]').fill("1")
    page.get_by_role("button", name="Launch", exact=True).click()
    page.wait_for_function(
        "document.querySelectorAll('pre')[document.querySelectorAll('pre').length-1]"
        ".innerText.split('\\n').filter(x=>x.trim()).length >= 2")
    log(f"streaming: {len(panel_lines(page))} lines rendered, killing socket now")
    page.screenshot(path=f"{OUT}/06-streaming.png")

    # -- 5. Kill the socket (devtools-equivalent): force-close the live WebSocket.
    page.evaluate("window.__lastWS.close()")
    page.wait_for_selector("text=(reconnecting)")
    log("socket killed: status=reconnecting; worker keeps publishing meanwhile")
    page.screenshot(path=f"{OUT}/07-dead.png")

    page.wait_for_selector("text=(live)", timeout=15000)
    log("socket reconnected (1.5s backoff): snapshot refetched, stream resumed")

    # -- 6. No gap, no dupes: every line exactly once after recovery.
    page.wait_for_function(
        "document.querySelectorAll('pre')[document.querySelectorAll('pre').length-1]"
        ".innerText.includes('✔ done')", timeout=30000)
    final = panel_lines(page)
    page.screenshot(path=f"{OUT}/08-recovered.png")

    assert len(final) == 9, f"expected 9 lines (8 log + done), got {len(final)}: {final}"
    assert final[0] == "cloning repository…", final[0]
    assert final[-1] == "✔ done", final[-1]
    assert len(set(final[:-1])) == 8, "duplicate lines detected"
    log(f"recovered panel shows all {len(final)} lines exactly once — no gap, no duplicates")
    log("PASS: full Phase 0 exit walkthrough")

    browser.close()

with open(f"{OUT}/transcript.txt", "w") as f:
    f.write("\n".join(transcript) + "\n")
print(json.dumps({"ok": True}))
